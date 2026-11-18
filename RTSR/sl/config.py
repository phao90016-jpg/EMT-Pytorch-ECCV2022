"""场景与模式参数 —— 全包唯一的参数来源。

这个包里**不允许**在别处硬编码任何场景数字：一个值只要用到两次，就必须定义在这里。

两个模式（conservative / ideal）把 README 第 2 节列出的十条「论文没说」的假设
打包成两套预设，避免每次跑实验都手工挑参数。
"""
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np


@dataclass
class Scenario:
    """物理场景。逐项对齐 ns-3 阶段的配置（见 README 第 4 节）。"""

    # ---- 拓扑 ----
    site_rings: int = 1            # 1 -> 7 个站 -> 21 个小区（统计只用中心这 21 个）
    interferer_rings: int = 1      # 额外的外圈站，只用来产生干扰（模拟 wraparound）
    isd_m: float = 200.0           # 站间距（米）
    sectors: int = 3               # 每站 3 扇区
    sector_bearings_deg: Tuple[float, ...] = (0.0, 120.0, 240.0)   # 三个扇区的朝向

    # ---- 射频 ----
    fc_ghz: float = 4.0            # 载频 4 GHz
    bw_mhz: float = 100.0          # 带宽 100 MHz
    scs_khz: float = 30.0          # 子载波间隔 30 kHz（numerology 1）
    tdd_dl_fraction: float = 0.7   # DDDSU 图样下行的占比：(3 个 DL + 半个 S) / 5
    tti_s: float = 0.5e-3          # 一个时隙 0.5 ms（30 kHz 下每时隙 14 个符号）
    gnb_power_dbm_per_20mhz: float = 44.0   # 论文写的 44 dBm/20 MHz
    gnb_height_m: float = 25.0     # 基站天线挂高
    ue_height_m: float = 1.5       # 终端高度
    nf_gnb_db: float = 5.0         # 基站噪声系数
    nf_ue_db: float = 9.0          # 终端噪声系数
    gnb_elements: int = 64         # 64 阵元（8x4 双极化）
    gnb_rows: int = 8              # 天线阵行数
    gnb_cols: int = 4              # 天线阵列数
    downtilt_deg: float = 12.0     # 下倾角
    element_hpdbw_deg: float = 65.0   # 阵元水平半功率波束宽度
    element_vpdbw_deg: float = 65.0   # 阵元垂直半功率波束宽度
    element_max_atten_db: float = 30.0  # 阵元方向图的最大衰减

    # ---- 终端 ----
    ue_per_cell: int = 6           # 每小区终端数
    indoor_ratio: float = 0.8      # 室内终端比例（论文设定 0.8）
    indoor_penalty_db: float = 20.0  # 室内穿透损耗
    ue_speed_kmh: float = 3.0      # 终端移动速度

    # ---- 运行控制 ----
    duration_s: float = 1000.0     # 仿真时长（秒）；M6 用的是 1000 s
    seed: int = 1                  # 随机种子

    # ---- 以下都是从上面推导出来的量，不要手工赋值 ----
    @property
    def n_rb(self) -> int:
        """资源块个数：带宽 / (子载波间隔 x 12 个子载波)。100 MHz/30 kHz 下是 273。"""
        return int(self.bw_mhz * 1e6 / (self.scs_khz * 1e3 * 12))

    @property
    def cell_bandwidth_hz(self) -> float:
        """小区带宽（Hz）。"""
        return self.bw_mhz * 1e6

    @property
    def rb_bandwidth_hz(self) -> float:
        """单个资源块的带宽（Hz）。"""
        return self.cell_bandwidth_hz / self.n_rb

    @property
    def gnb_power_dbm(self) -> float:
        """把论文的 44 dBm/20 MHz 按带宽折算到全带宽。

        功率谱密度不变，所以带宽扩大 5 倍要加 10log10(5) 约 7 dB。
        """
        return self.gnb_power_dbm_per_20mhz + 10.0 * np.log10(self.bw_mhz / 20.0)

    @property
    def noise_dbm_per_rb(self) -> float:
        """每个资源块上的热噪声功率（dBm）：-174 dBm/Hz + 10log10(BW) + 噪声系数。"""
        return (-174.0 + 10.0 * np.log10(self.rb_bandwidth_hz) + self.nf_ue_db)

    @property
    def noise_dbm_wideband(self) -> float:
        """全带宽上的热噪声功率（dBm）。"""
        return (-174.0 + 10.0 * np.log10(self.cell_bandwidth_hz) + self.nf_ue_db)

    @property
    def n_tti(self) -> int:
        """总共仿真多少个 TTI。1000 s / 0.5 ms = 2,000,000。"""
        return int(round(self.duration_s / self.tti_s))


@dataclass
class Mode:
    """README 第 2 节那十条假设，打包成两套预设。

    conservative（保守档）= 尽量贴近 ns-3 的实际能力（TDMA、非理想波束、查表链路）。
    ideal（理想档）      = 论文隐含的假设（OFDMA、理想波束、3GPP 曲线、O2I 模型）。
    """

    name: str = "conservative"

    # 假设 1：调度器
    scheduler: str = "tdma"        # "tdma" | "ofdma_pf"
    rbg_size: int = 8              # 每个资源块组含几个 RB

    # 假设 2：波束赋形
    ideal_beam: bool = False       # True = 服务链路拿到全部阵列增益（理想波束）

    # 假设 3：链路级抽象
    use_3gpp_curves: bool = False  # False = 用从 ns-3 反拟合出来的 SE 表

    # 假设 4：链路自适应
    olla: bool = False             # 外环链路自适应（补偿 CQI 偏差）
    cqi_period_tti: int = 20       # CQI 上报周期（TTI 数）

    # 假设 5：室内穿透
    o2i_model: bool = False        # True = 用 3GPP O2I 模型，False = 固定 20 dB 惩罚

    # 假设 6：模型质量 -> 帧大小反馈（B2，未实现）
    model_feedback: bool = False   # True = 帧长均值按 20.8 kB x (2 - q) 变化

    # 假设 7/8：PDB 的处理粒度
    pdb_granularity: str = "sdu"   # "sdu" = 旧的准入语义 | "frame" = 帧级送达语义

    # 假设 8b：邻区干扰抑制量（dB）。
    # 用 ns-3 实测的**每 UE** SINR 分布标定：6 UE/cell 时 p5 = 19.1 dB、p50 = 31.2 dB。
    # 不设这一项时，本仿真会把所有邻区的全带宽功率都算进干扰，低尾比 ns-3 悲观 16 dB。
    # 16 dB 不是按 FSR 目标凑的，是按 p5 对齐来的（详见 docs/stage3/01_差距分析.md 第 11 节）。
    icic_atten_db: float = 0.0

    # 假设 9：外圈 wraparound（避免边缘小区统计偏乐观）
    wraparound: bool = True

    # 假设 10：种子数
    n_seeds: int = 1

    @staticmethod
    def conservative() -> "Mode":
        """保守档：贴近 ns-3 的实际能力。"""
        return Mode(name="conservative")

    @staticmethod
    def ideal() -> "Mode":
        """理想档：论文隐含的假设组合。

        这六项一起打开才把容量从约 190 推到论文量级：
        OFDMA + 理想波束 + 3GPP 曲线 + OLLA + O2I 模型 + 帧级 PDB。
        """
        return Mode(
            name="ideal",
            scheduler="ofdma_pf",
            ideal_beam=True,
            use_3gpp_curves=True,
            olla=True,
            o2i_model=True,
            model_feedback=True,
            pdb_granularity="frame",
            icic_atten_db=16.0,
            wraparound=True,
            n_seeds=3,
        )