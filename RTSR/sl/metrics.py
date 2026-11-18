"""每 UE 的帧成功率、满意率与容量（README 第 5.1 节第 7 步）。

**两个指标必须分清，它们不是一回事：**

* ``mean_fsr_pct``（平均 FSR）= 所有中心 UE 的 FSR 的**算术平均**。
  论文 Fig.6 用的是这个。
* ``satisfied_pct``（满意率）= FSR > 99.5% 的 UE **占比**。
  论文 Fig.5 用的是这个。

两者没有函数关系：9 个 UE 里有 4 个 FSR=99.6%、5 个 FSR=99.4%，平均 FSR 仍是 99.49%
（看着很高），但满意率只有 44%（因为没有一个过 99.5%）。历史数据里出现过
"平均 FSR 98.27% 但满意率只有 39.68%"，就是这个原因。
"""
import numpy as np


def fsr_per_ue(traffic):
    """每 UE 的帧成功率 = 成功帧数 / 发送帧数。

    分母用 max(...,1) 防止除零（从未发过帧的 UE 记 0 而不是 NaN）。
    """
    sent = np.maximum(traffic.frames_sent, 1)
    return traffic.frames_ok / sent


def summary(traffic, topo, cells_per_ue_cell):
    """返回论文那两个指标，**只统计中心小区的 UE**（外圈只用来产生干扰）。"""
    m = topo.ue_is_centre
    fsr = fsr_per_ue(traffic)[m]
    sent = traffic.frames_sent[m]
    satisfied = fsr > 0.995        # 论文的判据：每 UE 的 FSR 超过 99.5% 才算满意
    return {
        "ues": int(m.sum()),
        "frames": int(sent.sum()),
        "mean_fsr_pct": float(100.0 * fsr.mean()) if len(fsr) else 0.0,
        "satisfied_pct": float(100.0 * satisfied.mean()) if len(fsr) else 0.0,
        "ue_per_cell": cells_per_ue_cell,
    }