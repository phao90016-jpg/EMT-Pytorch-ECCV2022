# RTSR 复现（WCNC 2023）

> *Real-Time Super-Resolution: A New Mechanism for XR over 5G-Advanced*（IEEE WCNC 2023）
> 的复现工程：**算法层**（轻量超分 + 在线训练）+ **网络层**（ns-3 + 5G-LENA，21 cell / 100 MHz / DDDSU）。

## 结论速览

| 指标 | 论文 | 本复现 |
|---|---|---|
| 6 UE/cell 满意率（传统 / RTSR）| 都 >90% | **96.83% / 100%** ✅ |
| 12 UE/cell 满意率 | 都 >90% | **传统 2.78% / RTSR 97.22%** ⚠️ 传统提前崩 |
| 18 UE/cell 满意率 | 传统崩塌 | 传统 **0%** ✅ |
| 拐点位置 | 17–18 | **~9.5**（容量 190 vs 论文 250–360 Mbps）|

**一句话**：趋势复现（传统先崩、RTSR 显著更抗压），但绝对拐点左移约一半，根因已定位到
**TDMA 调度器 + 模拟波束约束**（有代码证据）。

## 文档导航

| 文档 | 内容 |
|---|---|
| [`docs/01_论文与场景.md`](docs/01_论文与场景.md) | 论文参数逐项对照（唯一参数权威版）|
| [`docs/02_实现与偏差.md`](docs/02_实现与偏差.md) | 实现决策、满意率口径、**13 条偏差总表**、踩坑清单 |
| [`docs/03_结果与对照.md`](docs/03_结果与对照.md) | 所有结果数字与论文对照（唯一数字权威版）|
| [`docs/04_执行手册.md`](docs/04_执行手册.md) | 编译、运行、看进度、排错 |
| [`docs/05_答辩材料.md`](docs/05_答辩材料.md) | 一页纸提纲 + 详稿 + 7 个预设问答 |
| [`docs/06_路线与后续.md`](docs/06_路线与后续.md) | 两阶段路线、待办、成本模型 |
| [`algorithm/README.md`](algorithm/README.md) | 算法层工具与脚本 |

## 目录结构

```
RTSR/
├── docs/                 文档（01–06）
├── rtsr-simulation.cc    主仿真（拓扑/天线/业务/埋点）
├── rtsr-frame-agents.h   帧源与帧宿（FSR 统计）
├── layer_stats.py        五层丢包合并 + 一致性校验
├── scripts/              runner（串行/并行）、统计、状态脚本
├── patches/              ns-3 补丁（RLC 真正丢弃）
├── results/              每次运行的产物（layer_report.md + csv）
└── archive/              已合并的历史文档（只读）
```

## 快速开始

```bash
# 1) 编译（只需一次）
cd ~/code/ns-allinone-3.39/ns-3.39
./ns3 configure --build-profile=optimized && ./ns3 build

# 2) 跑一批（并行 3 路）
cd ~/code/EMT-Pytorch-ECCV2022
setsid nohup bash RTSR/scripts/p6_run_parallel.sh \
  RTSR/scripts/p6_manifest_batch2.txt 3 > /tmp/p6.log 2>&1 &

# 3) 看进度
bash RTSR/scripts/p6_status.sh
```

详见 [`docs/04_执行手册.md`](docs/04_执行手册.md)。

## 文档规则

1. **一个事实只在一处定义**，其他地方用链接引用；
2. 参数 → `01`；实现与偏差 → `02`；数字 → `03`；操作 → `04`；讲稿 → `05`；计划 → `06`；
3. 数字必须能从 `results/p6/summary2.csv` 复算出来，不手抄。
