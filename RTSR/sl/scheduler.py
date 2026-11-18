"""每小区调度器（README 第 5.1 节第 3 步）。

两个模式都用比例公平（PF）度量。为什么不用 max-rate：一旦有真实业务，
贪心调度会把除一个 UE 之外的所有人都饿死，和论文、和 ns-3 阶段的行为都不像。

``tdma``    : 每 TTI 只服务 ``served_per_tti`` 个 UE（轮询），且只填
              ``rb_budget`` 这么多 RB。ns-3 阶段的 TDMA-QoS 每 TTI 发约 2.5 个
              TB、每个约 29 RB，也就是 273 个 RB 里的三分之一 —— 这正是它
              卡在约 190 Mbps 的原因。
``ofdma_pf``: 每个 RBG 都分给 PF 度量最好的 UE，整带每 TTI 都用满。
"""
import numpy as np


class Scheduler:
    def __init__(self, sc, mode, topo):
        self.sc = sc
        self.mode = mode
        self.topo = topo
        self.n_rb = sc.n_rb
        self.rbg_size = mode.rbg_size
        self.n_rbg = int(np.ceil(self.n_rb / self.rbg_size))

        # ---- 保守档（TDMA）的固定授权大小 ----
        # 对齐 ns-3 阶段：每个 TB 约 29 RB、每个下行 TTI 约 4 个 TB。
        self.grant_rb = 68
        # 每 TTI 可用于 TDMA 的 RB 占比。
        # 这个系数是**标定出来的**：0.5 时容量只有 154.7 Mbps（2026-11 的
        # FSR/traffic 重构之后），调到 0.61 才重新对上 ns-3 的约 190 Mbps。
        self.rb_budget_fraction = 0.61
        self.rb_budget = max(1, int(round(self.rb_budget_fraction * self.n_rb)))
        self.served_per_tti = 2
        self.rb_utilization = (self.grant_rb * self.served_per_tti) / float(self.n_rb)

        self.avg_rate = np.ones(topo.n_ue)     # PF 用的历史平均速率
        self.decay = 0.98                      # 平均速率的指数遗忘因子

        # TDMA 在小区内按轮询顺序服务。早期版本用"记忆 25 ms 的 PF 度量"，
        # 结果会把某些 UE 饿超过 10 ms 的 PDB —— 低载时每一帧都超时，就是这么来的。
        self._rr = np.zeros(topo.n_cells, dtype=int)

        # 低于这个字节数的 UE 不给授权：按 6 s 摊平的模型流会让每个 RTSR UE
        # 永远"有数据"，白白把授权浪费在几十个字节上。
        self.min_tx_bytes = 2000.0

    # ------------------------------------------------------------------ 主入口
    def schedule(self, sinr_db, link, backlog_bytes, frame_backlog=None):
        """返回本 TTI 的授权列表：[(小区号, 被调度的 UE 索引数组, 各自分到的 RB 数)]。"""
        grants = []
        for ci in range(self.topo.n_cells):
            ues = self.topo.cell_ues[ci]
            if len(ues) == 0:
                continue

            # 只保留"有足够数据填满一次有意义的授权"的 UE
            if frame_backlog is not None:
                keep = (frame_backlog[ues] > 0.0) | (backlog_bytes[ues] >= self.min_tx_bytes)
            else:
                keep = backlog_bytes[ues] > 0.0
            ues = ues[keep]
            if len(ues) == 0:
                continue

            if self.mode.scheduler == "tdma":
                # 轮询：每 TTI 取 served_per_tti 个 UE。
                # 授权大小按该 UE 的积压来定，让一帧在一到两次服务内排空
                # （下一帧到达之前缓冲就空了）；但每小区每 TTI 的总量仍受
                # rb_budget 限制。
                take = min(self.served_per_tti, len(ues))
                picked = np.array([int(ues[(self._rr[ci] + j) % len(ues)])
                                   for j in range(take)])
                self._rr[ci] += take
                se = np.maximum(link.se(sinr_db[picked]), 0.1)
                # 1 个 RB 在 1 个 TTI 内能装多少字节：SE(b/RE) x 12 子载波 x 12 符号 / 8
                bytes_per_rb = se * 12 * 12 / 8.0
                need = np.ceil(backlog_bytes[picked] / bytes_per_rb)
                budget = int(self.rb_budget)
                share = np.full(take, budget // max(take, 1))
                n_rb = np.clip(need.astype(int), 1, None)
                n_rb = np.minimum(n_rb, share)      # 不超过本次能分到的份额
                grants.append((ci, picked, n_rb))
            else:
                grants.extend(self._ofdma_pf(ci, ues, sinr_db, link))
        return grants

    # ------------------------------------------------------------------ 比例公平
    def _ofdma_pf(self, ci, ues, sinr_db, link):
        """OFDMA 的比例公平分配：每个有数据的 UE 先拿均分，余下的给 PF 度量最高的。

        早期版本是"每个 RBG 做一次 argmax"的贪心循环，占了整个运行时间的 68%；
        改成这个闭式分配后快了一个数量级，结果几乎一样。
        """
        rbg_rb = self.rbg_size
        se = link.se(sinr_db[ues])
        inst = se * rbg_rb * 12 * 12 / 8.0                 # 该 RBG 的瞬时可达字节
        metric = inst / np.maximum(self.avg_rate[ues], 1e-9)   # PF 度量

        n = len(ues)
        base = self.n_rbg // n
        alloc = np.full(n, base, dtype=int)
        rest = self.n_rbg - base * n
        if rest > 0:
            alloc[np.argsort(-metric)[:rest]] += 1
        sel = alloc > 0
        if not np.any(sel):
            return []
        return [(ci, ues[sel], alloc[sel] * rbg_rb)]

    def update_rates(self, grants, sizes_bytes):
        """用本 TTI 实际发出去的字节更新 PF 的历史平均速率。"""
        self.avg_rate *= self.decay
        for (ci, ues, n_rb), (u_sel, bytes_) in zip(grants, sizes_bytes):
            self.avg_rate[u_sel] += (1.0 - self.decay) * bytes_