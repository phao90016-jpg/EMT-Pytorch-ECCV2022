# RTSR 复现记录：网络层（Network Layer）

> **总报告：[`RTSR_TOTAL_REPORT.md`](RTSR_TOTAL_REPORT.md)** —— 算法层 + 网络层的完整结果、结论与偏差声明。
> **逐条对照：[`RTSR_复现对照表.md`](RTSR_复现对照表.md)** —— 论文每一节/每张表做到了什么、差距在哪。

本目录记录 WCNC 2023 论文《Real-Time Super-Resolution: A New Mechanism for XR over 5G-Advanced》的网络层复现工作。

当前重点：验证 5G-Advanced 网络中的**分层 QoS 传输机制**——无线资源受限并发生拥塞时，优先保障 XR 视频流，让低优先级的 SR 模型更新流承担更多丢包。

> 算法层（EDSR M1/M2/M3、模型尺寸-PSNR）在 `EDSR-PyTorch/`，见 `TABLE1.md` 与 `DT_SWEEP.md`。

## 仿真环境

- WSL2 Ubuntu 24.04
- ns-3.39 + 5G-LENA v2.5，NR 模块位于 `ns-3.39/src/nr/`
- 核心代码：[`rtsr-simulation.cc`](rtsr-simulation.cc)，改自 5G-LENA 示例 `cttc-nr-traffic-3gpp-xr.cc`

## 代码修改点

- **双流架构**：在 3GPP XR 业务（AR/VR/CG）之外，新增周期性 SR 模型流；单次 **530 个 1024 B 报文 = 530 KiB**，每 **6 秒**一次，目标端口 **5000**。
- **分层 QoS 映射**：XR 业务 → `NGBR_LOW_LAT_EMBB`（5QI 80，高优先级）；SR 模型 → `NGBR_VIDEO_TCP_DEFAULT`（5QI 9，低优先级）。
- **拥塞构造**：带宽 **5 MHz**，`LteRlcUm::MaxTxBufferSize` = **500 KiB**。
- **QoS 调度器**：`NrMacSchedulerTdmaQos` + `NrMacSchedulerLcQos`。
- **统计**：FlowMonitor 逐流输出 Tx/Rx 字节、吞吐、时延、抖动。

## 当前仿真配置 vs 论文 Table III

| 项 | 当前值 | 论文 Table III |
|---|---|---|
| 小区数 / 站间距 | 1 个 gNB，无干扰 | 21 cell wraparound，ISD 200 m |
| 带宽 / SCS | 5 MHz / 15 kHz（numerology 0） | 100 MHz / 30 kHz |
| 载频 / 发射功率 | 4 GHz / 41 dBm | 4 GHz / 44 dBm per 20 MHz |
| 天线 | 4×8 双极化，downtilt 0° | 64Tx/4Rx，MU-MIMO，downtilt 12° |
| UE 数 | 1 AR + 1 VR + 1 CG | 按 UE 密度扫描（0–30/cell） |
| UE 分布 | 静态 | 80% 室内 / 20% 室外，3 km/h |
| 仿真时长 | 60 s | 1000 s |
| PDB | 未实现（仅 RLC 缓冲上限） | 帧 10 ms / 模型 50 ms |

## 已观测结果（60 s，5 MHz，500 KiB 缓冲，3 UE）

| 流类型 | 发送 | 接收 | 投递率 | 平均时延 |
|---|---:|---:|---:|---:|
| XR 视频（高优先级） | 114.47 MB | 113.69 MB | **99.3%** | ~450 ms |
| SR 模型（低优先级） | 15.95 MB | 14.31 MB | **89.7%** | ~668 ms |

**结论**：低优先级 SR 流承担了约 10% 丢包，高优先级 XR 流保持 99% 以上——分层 QoS 的机制方向得到验证。

**但这组数字不是论文的性能结论**：平均时延 450 ms 远超 10 ms PDB，说明处在深度饱和区间；它证明的是"优先级排序生效"，不是"系统容量提升"。论文 Fig.5/6 需要多小区、正常负载和帧级统计。

## 流量节省（实测字节，2026-10-19 重新仿真）

```bash
cd RTSR
python3 calc_traffic_saving.py --ns3-log /tmp/rtsr_ns3.log --duration 60 --ues 3
```

脚本解析 FlowMonitor 输出，按目标端口 5000 区分 SR 模型流；**没有日志就直接报错退出，不再编数字**。

| 项（每 UE，60 s） | 数值 | 来源 |
|---|---:|---|
| LD 视频 发送 / 接收 | 38.16 / 37.90 MB（5.09 Mbps） | 实测 |
| SR 模型 发送 | 5.32 MB（10 次更新 × 530 KiB） | 实测 |
| **RTSR 合计** | **43.48 MB** | 实测 |
| 传统 HD 基线 | 76.31 MB | **假设** LD×2（20 vs 10 Mbps） |
| **流量节省** | **43.0%** | |

更新周期敏感性（每 UE，模型 530 KiB，LD 实测 5.09 Mbps）：

| ΔT | 模型开销 | 流量节省 |
|---|---:|---:|
| 2 s | 2.07 Mbps | 29.7% |
| 6 s | 0.69 Mbps | **43.2%** |
| 10 s | 0.41 Mbps | 45.9% |
| 30 s | 0.14 Mbps | 48.6% |
| 60 s | 0.07 Mbps | **49.3%** |

**关键结论**：论文的"最高节省 50%"对应的是 **ΔT ≈ 30–60 s**；ΔT=6 s 时实测只有 **43%**，因为 0.69 Mbps 的模型开销占掉了 5.09 Mbps 视频预算的 **13.6%**。这正好回答了论文的 Q2（更新频率 vs LD 压缩度的折中）。

⚠️ 两个必须声明的假设：① HD 流没有被仿真，是用 LD 乘 2 推的；② 每 UE 假设收到同一条流。

## 如何运行

```bash
set -euo pipefail
NS3_DIR="/home/penghao/code/ns-allinone-3.39/ns-3.39"
SOURCE_FILE="/path/to/EMT-Pytorch-ECCV2022/RTSR/rtsr-simulation.cc"
TARGET_FILE="$NS3_DIR/src/nr/examples/cttc-nr-traffic-3gpp-xr.cc"

cp "$SOURCE_FILE" "$TARGET_FILE"
cd "$NS3_DIR"
./ns3 build
./ns3 run cttc-nr-traffic-3gpp-xr > /tmp/rtsr_ns3.log 2>&1
cd /path/to/EMT-Pytorch-ECCV2022/RTSR
python3 calc_traffic_saving.py --ns3-log /tmp/rtsr_ns3.log --duration 60 --ues 3
```

## 与论文的差距

| 论文章节 | 缺什么 |
|---|---|
| Fig.2 / §II-C | 式(1)(3) 的 required-rate 调度（f=10 视频 / f=1 模型）未实现，只有承载级优先级 |
| Table III | 21 cell / 100 MHz / 64T4R / 移动性 / 室内外比例 |
| Fig.5 | 帧级 PDB 丢弃统计、满意 UE 比例、容量扫描（0–30 UE/cell，1000 s） |
| Table II | 属算法层：需按 3–5 Mbps 编码 LD 视频并测 PSNR/VMAF |

## 下一步

- [x] 双流 + 分层 QoS 仿真环境
- [x] SR 模型流周期性发送（530 KiB / 6 s）
- [x] 流量节省改为解析 FlowMonitor 实测字节（per-UE 口径）
- [x] 算法层 Table I（M1/M2/M3）
- [ ] 多小区 + 帧级统计，复现 Fig.5/6
- [ ] 式(1)-(3) required-rate 调度

## P1：算法层复现（2026-10-20）

结果与代码分别在：

- [`results/`](results/) —— TABLE1 / TABLE1_4K / TABLE2 / TABLE2_4K / DT_SWEEP / P1_REPORT
- [`algorithm/`](algorithm/) —— EDSR 侧的工具、运行脚本与两处源码补丁

| 实验 | 结果 |
|---|---|
| Table I（540p→1080p） | M1 33.057 / M2 35.702 / M3 39.216 dB |
| Table I（1080p→2160p，干净 bicubic） | 44.506 / 45.367 / 46.303 dB |
| Table I（1080p→2160p @5 Mbps） | 41.501 / 42.295 / 42.833 dB |
| Table II（1080p→2160p，3–5 Mbps，含 VMAF） | PSNR 41.05–42.30，VMAF 88.61–90.99 |
| 在线训练窗 60/180/400 帧 | 35.699 / 35.705 / 35.709 dB |

**结论**：M2→M3 的每翻倍增益随任务难度单调下降（0.275 → 0.179 → 论文 0.075），
"压缩退化使容量收益变平"得到验证；VMAF 在 5 Mbps 处为 90.99，论文 90.09。
完整偏差声明见 `results/P1_REPORT.md` 第四节。


## P2：容量扫描（单小区）

`capacity_sweep.py` 按 UE 密度重复运行仿真，解析 FlowMonitor 后计算每 UE 投递率、
满意 UE 比例（投递率 >= 99.5%），结果见：

- `capacity_sweep_summary.md` —— 5 MHz 与 100 MHz 的对照与结论
- `capacity_sweep_5mhz.md` / `capacity_sweep_100mhz.md` —— 原始表
- `capacity_sweep_{5,100}mhz.json` —— 结构化数据

```bash
python3 capacity_sweep.py --bandwidth 100 --numerology 1 --ues 1 2 3 --tag 100mhz
```

要点：5 MHz 在 3 个 UE 即饱和（344 ms、80% 满意），6 个 UE 崩溃；
100 MHz 在 6 个 UE 仍 2 ms / 100%。单小区、无 wraparound，不能对论文 Fig.5 的绝对值。

## 补充材料（2026-10-21）

| 文件 | 内容 |
|---|---|
| `results/latency.md` | 单帧推理时延（6 组：M1/M2/M3 × 1080p/2160p 输出） |
| `results/seed_variance.md` | 3 个随机种子的方差检验 |
| `results/fig4_snapshot.png` / `fig4_zoom.png` | 论文 Fig.4 的主观对比图 |
| `RTSR_复现对照表.md` | 论文全部内容 ↔ 复现情况逐条对照 |
| `答辩提纲.md` | 一页纸 + 7 个预设问答 |
