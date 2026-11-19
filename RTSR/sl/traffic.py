"""XR 帧业务、RTSR 模型更新流，以及 10 ms PDB（README 第 6 节）。

**FSR 的口径由 `mode.pdb_granularity` 决定，这是整个项目最容易搞错的地方：**

* ``"frame"`` —— 论文 / ns-3 的口径，理想档在用：
  每一帧自带自己的截止时间。只有当这一帧的**全部字节**都在 ``到达时刻 + 10 ms``
  之前被服务完，才算成功；否则整帧作废、计一次失败。
  这和 ns-3 阶段的 ``complete / sent`` 完全一致，也对应论文原文
  "if the waiting time of the frame at BS buffer exceeds 10ms, it will be dropped"。

* ``"sdu"`` —— 旧口径，只为复现保守档的历史标定才保留：
  新帧到达时，如果**队列里最老的那一字节**已经等了超过 PDB，就拒收这个新帧，
  而且**准入即记成功**。这算的是"准入率"不是"送达率"，会高估约 5 个百分点。

帧字节与模型更新字节**分开排队**：只有帧字节参与队首等待的计算，
所以按 6 s 摊平的模型流不会把视频队列"占住"。
"""
import numpy as np

# 每个 UE 最多同时有几帧在飞。10 ms PDB + 16.7 ms 帧间隔下最多只会有两帧排队，
# 取 4 已经很宽松，而且让每 TTI 的计算可以在固定的 (n_ue, SLOTS) 数组上向量化。
SLOTS = 4


class Traffic:
    def __init__(self, sc, mode, topo, seed=None, capacity_mbps_per_cell=190.0):
        self.sc = sc
        self.mode = mode
        self.topo = topo
        rng = np.random.default_rng((seed if seed is not None else sc.seed) + 2000)
        self.rng = rng

        self.fps = 60.0                                  # 帧率
        self.frame_interval = 1.0 / self.fps             # 16.667 ms
        self.pdb_tti = int(round(0.010 / sc.tti_s))      # 10 ms 折成 20 个 TTI
        self.frame_level = (getattr(mode, "pdb_granularity", "sdu") == "frame")

        self.bitrate_mbps = 20.0                         # 每 UE 视频码率
        self.model_bytes_per_s = 0.0                     # 模型流速率（按需设置）
        self.model_bytes_per_tti = 0.0

        n = topo.n_ue
        self.n_ue = n

        # --- 帧队列：(n_ue, SLOTS) 的定长数组，避免每 TTI 建 Python 对象 ---
        self.frame_rem = np.zeros((n, SLOTS))            # 该帧还剩多少字节没发
        self.frame_deadline = np.zeros((n, SLOTS), dtype=np.int64)   # 该帧的截止 TTI
        self.frame_alive = np.zeros((n, SLOTS), dtype=bool)          # 该槽位是否有活帧

        # 旧口径（准入率）用的记账：队首开始等待的 TTI，-1 表示队列空
        self.hol_tti = np.full(n, -1, dtype=np.int64)

        self.model_backlog = np.zeros(n)                 # 模型流积压
        self.next_arr_tti = np.zeros(n, dtype=np.int64)  # 下一次帧到达的 TTI
        self.now_tti = 0
        self._schedule_next_arrival(np.arange(n), 0)

        self.frames_sent = np.zeros(n, dtype=np.int64)   # FSR 的分母
        self.frames_ok = np.zeros(n, dtype=np.int64)     # FSR 的分子
        # 诊断用：4 个槽位全占满时新到达的帧会被静默丢弃（已计入 sent 但永远不会成功）。
        # 这个计数器用来判断：失败里有多少其实是队列溢出，而不是真的超时。
        self.frames_noslot = np.zeros(n, dtype=np.int64)

    # ------------------------------------------------------------- 帧到达
    def _schedule_next_arrival(self, idx, now_tti):
        """按 16.667 ms 名义间隔 + 截断抖动，算出这批 UE 下一帧的到达 TTI。

        抖动是 N(0, 2 ms) 并截断在 ±4 ms，和 ns-3 阶段的设定一致。
        """
        jitter = np.clip(self.rng.normal(0.0, 0.002, size=len(idx)), -0.004, 0.004)
        step = np.maximum(
            1, np.round((self.frame_interval + jitter) / self.sc.tti_s).astype(np.int64)
        )
        self.next_arr_tti[idx] = now_tti + step

    def _frame_bytes(self, n):
        """抽帧长：均值 41.7 kB，标准差 10.5%，截断在 [0.5, 1.5] 倍均值。"""
        mean = self.bitrate_mbps * 1e6 / 8.0 / self.fps
        return np.clip(self.rng.normal(mean, 0.105 * mean, size=n), 0.5 * mean, 1.5 * mean)

    # ------------------------------------------------------------- 每 TTI
    def step(self, now_tti):
        """推进一个 TTI：先让过期帧作废，再处理新到达的帧。"""
        self.now_tti = now_tti
        if self.model_bytes_per_tti > 0:
            self.model_backlog += self.model_bytes_per_tti

        # 1) 过期帧作废（论文口径：等待超过 PDB 就丢）
        if self.frame_level:
            expired = self.frame_alive & (now_tti > self.frame_deadline)
            if np.any(expired):
                self.frame_alive[expired] = False
                self.frame_rem[expired] = 0.0

        # 2) 处理到期的帧到达
        due = self.next_arr_tti <= now_tti
        if np.any(due):
            idx = np.flatnonzero(due)
            sizes = self._frame_bytes(len(idx))
            self.frames_sent[idx] += 1          # 分母在这里加

            if self.frame_level:
                # 找一个空槽位放新帧；没有空槽位的帧直接算失败（从未成功过）
                free = ~self.frame_alive[idx]
                has = free.any(axis=1)
                slot = free.argmax(axis=1)
                sel = idx[has]
                if np.any(~has):
                    self.frames_noslot[idx[~has]] += 1
                self.frame_alive[sel, slot[has]] = True
                self.frame_rem[sel, slot[has]] = sizes[has]
                self.frame_deadline[sel, slot[has]] = now_tti + self.pdb_tti
            else:
                # 旧口径：队首等待超时则拒收新帧，但"准入即成功"
                hol_wait = np.where(self.hol_tti[idx] >= 0, now_tti - self.hol_tti[idx], 0)
                admit = hol_wait <= self.pdb_tti
                self.frames_ok[idx[admit]] += 1
                self._push_legacy(idx, np.where(admit, sizes, 0.0), now_tti)

            self._schedule_next_arrival(idx, now_tti)

    def _push_legacy(self, idx, add, now_tti):
        """旧口径的入队逻辑：只有队列从空变非空时才记队首开始等待的时刻。"""
        backlog = self.frame_rem[idx].sum(axis=1)
        started = (backlog <= 0) & (add > 0)
        self.hol_tti[idx[started]] = now_tti
        free = ~self.frame_alive[idx]
        has = free.any(axis=1) & (add > 0)
        slot = free.argmax(axis=1)
        sel = idx[has]
        self.frame_alive[sel, slot[has]] = True
        self.frame_rem[sel, slot[has]] = add[has]
        self.frame_deadline[sel, slot[has]] = now_tti + self.pdb_tti

    # ------------------------------------------------------------- 服务
    def serve(self, served_bytes):
        """把本 TTI 调度到的字节先喂给帧（最早截止优先），再喂给模型流。

        因为每帧的截止时间 = 到达时刻 + 常数，最早截止优先在这里等价于先进先出。
        只有在 ``frame_level`` 口径下，把一帧**全部发完**才计一次成功——
        这就是 FSR 的分子。
        """
        avail = served_bytes.copy()
        rows = np.arange(self.n_ue)
        # 最早截止优先 == FIFO，因为 deadline = 到达时刻 + 常数
        order = np.argsort(
            np.where(self.frame_alive, self.frame_deadline, np.iinfo(np.int64).max), axis=1
        )
        for j in range(SLOTS):
            k = order[:, j]
            need = self.frame_rem[rows, k]
            if not np.any(need > 0):
                continue
            take = np.minimum(need, avail)       # 本 TTI 能给多少就给多少
            self.frame_rem[rows, k] -= take
            avail -= take
            if self.frame_level:
                # 帧级口径：整帧发完才算成功
                done = self.frame_alive[rows, k] & (self.frame_rem[rows, k] <= 1e-9)
                if np.any(done):
                    self.frames_ok[rows[done]] += 1
                    self.frame_alive[rows[done], k[done]] = False
            else:
                # 旧口径：只要该帧的字节被清空就释放槽位（成功在到达时已经记过了）
                emptied = self.frame_rem[rows, k] <= 1e-9
                if np.any(emptied):
                    self.frame_alive[rows[emptied], k[emptied]] = False
                    self.hol_tti[rows[emptied]] = -1

        # 帧都喂完了，剩余带宽才给模型流
        self.model_backlog = np.maximum(self.model_backlog - avail, 0.0)

    def drop_expired(self):
        """保留这个空方法只为 API 兼容；过期处理已经放进 step() 里了。"""

    def reset_counters(self):
        """清零计数器，**同时丢掉在飞的帧**。

        为什么要丢在飞的帧：一帧如果在 warm-up 边界之前到达，它的 ``frames_sent``
        会被清零，但它的完成事件仍然会给 ``frames_ok`` 加一 —— 结果就是
        最快的那批 UE 上出现 FSR > 100%（ok = sent + 1）的荒谬现象。
        """
        self.frames_sent[:] = 0
        self.frames_ok[:] = 0
        self.frames_noslot[:] = 0
        self.frame_alive[:] = False
        self.frame_rem[:] = 0.0
        self.model_backlog[:] = 0.0
        self.hol_tti[:] = -1

    # ------------------------------------------------------------- 对外视图
    @property
    def frame_backlog_bytes(self):
        """每 UE 还欠多少帧字节（调度器要用它做决策）。"""
        return self.frame_rem.sum(axis=1)

    @property
    def backlog_bytes(self):
        """每 UE 的总积压 = 帧 + 模型流。"""
        return self.frame_backlog_bytes + self.model_backlog