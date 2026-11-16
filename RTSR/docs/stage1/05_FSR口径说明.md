# 05 · FSR 口径说明（唯一权威版）

> 回答"FSR 到底怎么算、判在哪一层"。数字见 [`03_结果与对照.md`](03_结果与对照.md)。

## 1. 一句话

**FSR 是两级判定**：丢帧判在 gNB 的 RLC 层（QCI 68 的 10 ms discard timer），成功判在 UE 的应用层（整帧收齐），两者都过才算成功帧。

## 2. 计算链

```
① 源端应用层  XrFrameSource：每 1/60 s 生成一帧 → framesSent++
      │  PDCP → RLC（QCI 68）
② gNB RLC 缓冲 ← 第一级判定：队首等待 > 10 ms → 丢弃该帧剩余 SDU
      │          数据：rlc_drops.csv（TxDrop trace）
      │  MAC 调度 + HARQ 重传
③ PHY → 空口 → UE
      │
④ UE 应用层   XrFrameSink：收齐该帧全部 SDU → complete = 1
      │          ← 第二级判定：完整性
      │          数据：frame_per_ue.csv
⑤ 统计        FSR = complete / framesSent（每 UE）
```

## 3. 论文原文对照

| 论文原文 | 我们的实现 |
|---|---|
| "The PDB for each frame is 10ms, indicating that if **the waiting time of the frame at BS buffer** exceeds 10ms, it will be dropped." | QCI 68 → ns-3 `LteRlcUm` discard timer = 10 ms，在 gNB RLC 层丢 |
| "The PDB of DNN in RTSR is set to **50 ms**." | ⚠️ 目前用 QCI 9 默认的 **300 ms**（待修，见 §6）|
| "a UE is deemed to be satisfied that **the rate of success frame** is larger than 99.5%" | `p6_stats.py:98` |
| "the ratio of successful frames over total frames"（Fig.6）| `complete / sent` |

**关键**：论文写的是 "waiting time at BS buffer"，**不是端到端**。我们报的"论文口径"就是这个。

## 4. 代码位置

| 环节 | 文件:行 |
|---|---|
| 帧源（60 FPS、截断高斯、抖动）| `rtsr-frame-agents.h:203` |
| 视频承载 QCI 68（PDB 10 ms）| `rtsr-simulation.cc:1914` → `eps-bearer.cc:198` |
| RLC 丢弃 trace | `rtsr-simulation.cc:154` `RlcDropCallback` |
| 完整性判定 | `rtsr-frame-agents.h:458` |
| FSR 与满意率 | `scripts/p6_stats.py:94-99` |
| 五层合并 | `layer_stats.py` |
| 阶段二对应 | `sl/traffic.py`（HOL 拒帧）、`sl/metrics.py`（每 UE FSR）|

## 5. 平均 FSR 与满意率不是一回事

FSR 是**每个 UE 一个值**；"平均 FSR"只是把这些值取平均后的汇总数。

- **Fig.6**：对全部 UE 的 FSR 取平均
- **Fig.5**：数有多少个 UE 的**自身** FSR > 99.5%

两者没有函数关系——同一个均值可以对应完全不同的满意率（9 点均值 98.27% 但满意率仅 39.68%，因为 113/189 个 UE 卡在 90–99.5%）。

## 6. 已知边界（必须声明）

| 项 | 状态 |
|---|---|
| **DNN 推理不在环内** | 仿真只到 UDP 收包，UE 端 SR 计算未建模。实测 1080p 输出 20.6/52.8 ms、2160p 91.9/218.6 ms，均超 60 FPS 的 16.7 ms 预算 |
| **模型流 PDB** | 论文 50 ms，我们用 QCI 9 的 300 ms → 高估模型送达率（不影响视频 FSR）|
| **PDB 丢弃粒度** | 论文按整帧，我们按 SDU 再归属到帧（偏差 #8）|
| **DNN 对 FSR 的作用** | 仅两个参数：帧码率 10 Mbps（帧大小）、模型流 530 KB/6 s |

论文 II-C 明确："if one of SR models is not successfully received, UE can still watch the low-quality frame without SR enhancement" —— **模型丢失不影响帧成功率，只降画质**。这是 FSR 与 DNN 解耦的依据。