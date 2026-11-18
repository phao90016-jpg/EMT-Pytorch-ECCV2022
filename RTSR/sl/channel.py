"""路损、阴影、穿透、波束增益、小区活跃度与 SINR（README 第 5.1 节）。

**静态部分只算一次**（路损 + 阴影 + 穿透 + 波束），运行期只刷新快衰落和每 TTI 的
小区活跃度。3 km/h、4 GHz 下多普勒约 11 Hz（相干时间约 45 ms），所以每 90 个 TTI
刷新一次衰落就够，跑得快很多。
"""
import numpy as np

from .topology import Topology, wrap_to_pi


class Channel:
    def __init__(self, sc, mode, topo: Topology, load_per_cell_mbps: float = None):
        self.sc = sc
        self.mode = mode
        self.topo = topo
        rng = np.random.default_rng(sc.seed + 1000)

        # ---- 三维距离：二维距离 + 基站与终端的高度差 ----
        d2 = topo.distances()
        h = sc.gnb_height_m - sc.ue_height_m
        self.d3 = np.sqrt(d2 ** 2 + h ** 2)

        # ---- 视距判决：按 3GPP TR 38.901 的 LOS 概率随机决定每条链路 ----
        los = self._los_probability(self.d3) > rng.random(self.d3.shape)
        self.los = los
        self.path_loss_db = np.where(los, self._pl_los(self.d3), self._pl_nlos(self.d3))

        # ---- 阴影衰落：LOS 用 4 dB、NLOS 用 6 dB 标准差 ----
        sigma = np.where(los, 4.0, 6.0)
        self.shadow_db = rng.normal(0.0, 1.0, self.d3.shape) * sigma

        # ---- 室内穿透：始终是**分布**，不是固定值 ----
        # TR 38.901 7.4.3 里穿透损耗 = 墙体损耗 + 与室内深度成正比的项。
        # 理想档用低损墙（10 dB），保守档用高损墙（20 dB，即论文给的数），
        # 但两者都保留深度变化。原因：如果给所有室内终端一个固定惩罚，
        # 它们会被整批压到同一个劣势位置，造出一个任何调度都救不回来的 SINR 低尾。
        depth = rng.uniform(0.0, 25.0, self.d3.shape)      # 进入室内的深度（米）
        wall = 10.0 if mode.o2i_model else sc.indoor_penalty_db
        pen = wall + 0.5 * depth
        pen = np.where(topo.ue_indoor[:, None], pen, 0.0)   # 室外终端不扣
        self.penetration_db = pen

        self.beam_gain_db = self._beam_gain()

        # ---- 小区活跃度：一个小区有多大比例的 TTI 有数据可发 ----
        # 系统级阶段本该由调度器给出真实活跃度；在接入调度器之前，先按提供负载估算。
        # 这正是"终端越多、SINR 越低"这条耦合关系的来源。
        if load_per_cell_mbps is None:
            load_per_cell_mbps = sc.ue_per_cell * 20.0
        self.activity = float(np.clip(load_per_cell_mbps / 190.0, 0.02, 1.0))

        # ---- 邻区干扰抑制（波束零陷 / MU-MIMO 空域隔离）----
        # 下面的邻区项是"全带宽功率求和"，等于假设每个邻区在**每个 RB** 上都在干扰。
        # 有了波束赋形之后，这个假设在低尾比 ns-3 实测悲观 16 dB（见 Mode.icic_atten_db），
        # 所以理想档按 16 dB 折算干扰。注意：这个 16 dB 是按 ns-3 的**每 UE SINR 的 p5**
        # 标定的，不是按 FSR 目标反推的（详见 docs/stage3/01_差距分析.md 第 11 节）。
        self.icic_lin = 10.0 ** (-getattr(mode, "icic_atten_db", 0.0) / 10.0)
        self._rng = rng

        # ---- 静态接收功率：路损 + 阴影 + 穿透 + 波束，一次算好，运行期不变 ----
        self._p_rx_static = (sc.gnb_power_dbm
                             - self.path_loss_db
                             - self.shadow_db
                             - self.penetration_db
                             + self.beam_gain_db)

        self._fading = None
        self._p_lin = None                 # 缓存下来的线性功率矩阵
        self.coherence_tti = max(1, int(round(0.045 / sc.tti_s)))   # 45 ms 相干时间
        self.refresh_fading()
        self.tti_count = 0

    # ---------------------------------------------------------------- 传播模型
    @staticmethod
    def _los_probability(d_m: np.ndarray) -> np.ndarray:
        """3GPP UMa 的视距概率（TR 38.901 表 7.4.2-1）。"""
        d = np.maximum(d_m, 1.0)
        p = np.where(d <= 18.0, 1.0, 18.0 / d + np.exp(-d / 63.0) * (1.0 - 18.0 / d))
        return np.clip(p, 0.0, 1.0)

    def _pl_los(self, d_m: np.ndarray) -> np.ndarray:
        """UMa 视距路损。以断点距离 d_bp 为界，近段斜率 22、远段斜率 40。"""
        fc = self.sc.fc_ghz
        h_bs, h_ut = self.sc.gnb_height_m, self.sc.ue_height_m
        d_bp = 4.0 * (h_bs - 1.0) * (h_ut - 1.0) * (fc * 1e9) / 3e8
        d = np.maximum(d_m, 10.0)
        pl1 = 28.0 + 22.0 * np.log10(d) + 20.0 * np.log10(fc)
        pl2 = (28.0 + 40.0 * np.log10(d) + 20.0 * np.log10(fc)
               - 9.0 * np.log10(d_bp ** 2 + (h_bs - h_ut) ** 2))
        return np.where(d <= d_bp, pl1, pl2)

    def _pl_nlos(self, d_m: np.ndarray) -> np.ndarray:
        """UMa 非视距路损。"""
        fc = self.sc.fc_ghz
        d = np.maximum(d_m, 10.0)
        return (13.54 + 39.08 * np.log10(d) + 20.0 * np.log10(fc)
                - 0.6 * (self.sc.ue_height_m - 1.5))

    def _element_pattern_db(self, az_off, el_off) -> np.ndarray:
        """阵元方向图：水平与垂直各按 12*(偏离/HPBW)^2 dB 衰减，封顶 max_atten。"""
        sc = self.sc
        ah = -np.minimum(12.0 * (np.degrees(az_off) / sc.element_hpdbw_deg) ** 2,
                         sc.element_max_atten_db)
        av = -np.minimum(12.0 * (np.degrees(el_off) / sc.element_vpdbw_deg) ** 2,
                         sc.element_max_atten_db)
        return ah + av

    def _beam_gain(self) -> np.ndarray:
        """(n_ue, n_cells) 的波束增益矩阵，单位 dB。

        服务小区把波束**对准**该终端：阵元方向图 0 dB（正对）+ 阵列因子 10log10(N)。
        邻区的波束指向它自己的终端，所以对本终端只有阵元方向图的衰减
        （标准的系统级近似）。
        """
        sc, topo = self.sc, self.topo
        az = topo.azimuths()
        d = topo.distances()
        elev = np.arctan2(-(sc.gnb_height_m - sc.ue_height_m), np.maximum(d, 1.0))
        bearings = np.array([c.bearing_rad for c in topo.cells])[None, :]
        off = np.abs(wrap_to_pi(az - bearings))
        gain = self._element_pattern_db(off, elev + np.deg2rad(sc.downtilt_deg))

        array_db = 10.0 * np.log10(sc.gnb_elements)
        # 精确导向：服务链路看到的是正对方向（0 dB 阵元）加上阵列因子，
        # 而不是偏离方向的阵元衰减
        gain = gain.copy()
        gain[np.arange(topo.n_ue), topo.ue_cell] = array_db
        return gain

    # ---------------------------------------------------------------- 快衰落
    def refresh_fading(self, rng=None):
        """重新抽一次瑞利快衰落（指数分布，均值功率 1，即 0 dB）。"""
        rng = self._rng if rng is None else rng
        shape = self.d3.shape
        re = rng.normal(size=shape) / np.sqrt(2.0)
        im = rng.normal(size=shape) / np.sqrt(2.0)
        self._fading = re ** 2 + im ** 2          # 均值功率 1（0 dB）
        # 本次衰落对应的线性功率矩阵；下次刷新前一直复用
        self._p_lin = 10.0 ** ((self._p_rx_static
                                + 10.0 * np.log10(self._fading + 1e-12)) / 10.0)

    def advance(self):
        """每 TTI 调用一次；到相干时间就刷新衰落。"""
        self.tti_count += 1
        if self.tti_count % self.coherence_tti == 0:
            self.refresh_fading()

    # ---------------------------------------------------------------- SINR
    def rx_power_dbm(self) -> np.ndarray:
        """静态接收功率（不含快衰落），dBm。"""
        return (self.sc.gnb_power_dbm
                - self.path_loss_db
                - self.shadow_db
                - self.penetration_db
                + self.beam_gain_db)

    def sinr_db(self, active: np.ndarray = None) -> np.ndarray:
        """每终端的宽带 SINR（dB）。

        `active` 是 (n_cells,) 的布尔掩码，标记本 TTI 哪些小区在发射。
        传 None 表示所有小区都在发射（干扰上界）。
        用缓存的线性功率矩阵，所以每 TTI 的代价只有一次矩阵-向量乘。
        """
        p_lin = self._p_lin
        served = self.topo.ue_cell
        idx = np.arange(self.topo.n_ue)

        if active is None:
            active = np.ones(self.topo.n_cells, dtype=bool)
        act = active.astype(float)

        p_serv = p_lin[idx, served]                 # 服务小区的接收功率
        total = (p_lin * act).sum(axis=1)          # 所有活跃小区的总功率
        # 干扰 = 总功率 - 服务功率，再按 ICIC 系数折算
        interf = np.maximum(total - p_serv, 0.0) * self.icic_lin
        noise = 10.0 ** (self.sc.noise_dbm_wideband / 10.0)
        sinr = p_serv / (interf + noise)
        return 10.0 * np.log10(sinr + 1e-12)

    def sample_activity(self, rng=None, override: float = None) -> np.ndarray:
        """按活跃度随机决定本 TTI 哪些小区在发射。"""
        rng = self._rng if rng is None else rng
        a = self.activity if override is None else override
        return rng.random(self.topo.n_cells) < a