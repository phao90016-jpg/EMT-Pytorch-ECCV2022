# OFDMA 根因验证（阶段 0）

> 2026-11-19。目标：实证"OFDMA 在 5G-LENA 里失效，是因为所有 UE 共享同一个空波束编号"这一假设。
> 本文是阶段 A（量化波束网格）的准入依据，供审核。

## 1. 结论

**假设成立。** 根因是 `DirectPathBeamforming` 给每个 UE 都分配 `BeamId::GetEmptyBeamId()`，
导致调度器把全部 UE 归入**同一个波束组**，该组独占整段数据符号，组内所有 UE 在同一批符号上
按 RBG 复用——而 PHY 每个符号只能设一个波束，其余 UE 只能拿到旁瓣。

**修复点不在调度器，在波束算法。** 调度器的波束分组逻辑本身是正确的、可直接复用。

## 2. 证据链

### 2.1 源码：波束编号被写死为空

```cpp
// src/nr/model/ideal-beamforming-algorithm.cc:524-525
BeamformingVector gnbBfv =
    BeamformingVector(std::make_pair(gNbAntennaWeights, BeamId::GetEmptyBeamId()));
```

`DirectPathBeamforming` 的波束**矢量**是精确导向（逐 UE 对准），但**编号**永远是空。

### 2.2 实测：调度器确实只看到 1 个波束组

在 `NrMacSchedulerOfdma::GetSymPerBeam` 入口加了一次性打印（稳态 0.9 s 后），
3 小区 / 12 UE/cell / OFDMA-PF：

```
[BEAMGRP] activeDl.size()=1 symAvail=11
[BEAMGRP]   beam=First: [Sector: 0 elevation: 0] Second: [Sector: 0 elevation: 0] ues=9
```

| 观测 | 含义 |
|---|---|
| `activeDl.size() = 1` | 只有 **1 个波束组** |
| `beam = [Sector: 0, elevation: 0]` | 就是空波束编号 |
| `ues = 9` | 该组里有 **9 个活跃 UE** |
| `symAvail = 11` | 这 11 个符号**全部**给这一组 |

### 2.3 源码：组内所有 UE 共享全部符号

```cpp
// src/nr/model/nr-mac-scheduler-ofdma.cc:183-184, 200
uint32_t beamSym = symPerBeam.at(GetBeamId(el));      // = 11
uint32_t rbgAssignable = 1 * beamSym;
...
BeforeDlSched(ue, FTResources(rbgAssignable * beamSym, beamSym));   // 每个 UE 都拿到 11 个符号
```

`AssignDLRBG` 随后把**全部 RBG** 分给组内所有 UE（`while (resources > 0)` 循环）。
**结果是每个 UE 都在这 11 个符号上被分配了 RBG。**

### 2.4 实测：每符号 UE 数（决定性对比）

新增 `ues_per_symbol.csv`，统计每个 `(小区, 帧, 时隙, 符号)` 上出现几个不同 RNTI：

| 每符号 UE 数 | OFDMA-PF（符号数）| TDMA-QoS（符号数）|
|---:|---:|---:|
| 1 | 1 | 923 |
| 2 | 2 | **1,568** |
| 3 | 1 | 1,143 |
| 4 | 3 | 320 |
| 5–6 | 13 | 72 |
| 7–10 | 228 | 0 |
| **11** | **80** | 0 |
| **12** | **32** | 0 |
| **合计符号实例** | **360** | **4,027** |
| **峰值** | **11** | **2** |

**OFDMA 把 11 个 UE 塞进同一批符号，只用了 360 个符号实例；
TDMA 每符号最多 2 个 UE，摊到 4,027 个符号实例。**

### 2.5 后果：BLER 与交付率

同一次运行（3 小区，12 UE/cell，600 ms 有效传输）：

| 指标 | OFDMA-PF | TDMA-QoS |
|---|---:|---:|
| 调度 TB 数 | 8,652 | 11,146 |
| **PHY 损坏 TB** | **2,370** | **266** |
| **BLER** | **27.4%** | **2.4%** |
| 视频包发送 | 38,543 | 38,543 |
| **视频包接收** | **22,648** | **34,369** |
| **交付率** | **58.8%** | **89.2%** |

旁瓣数值对照：OFDMA 相对 TDMA 的 SINR 下降 **13.81 dB**（历史实测），
8×8 均匀阵第一旁瓣理论值 **13.26 dB**，差 **0.55 dB**。

## 3. 修复方向

**只需让波束编号反映真实方向。** 调度器、PHY、信道模型都不用改。

方案：新增 `QuantizedDirectPathBeamforming`，把 UE 相对小区朝向的方位角量化成扇区编号：

```
sector = 1 + floor((az + 60°) / gridDeg)      // 从 1 起，避开空编号 (0,0)
elevation = floor(el / gridDeg) * gridDeg
```

这样：
- 同扇区的 UE → 同一波束组 → 共享符号（OFDMA 复用）
- 不同扇区 → 不同波束组 → 各自独立的符号块 → 波束不用转

**波束网格宽度是关键旋钮**：网格越粗，同组 UE 越多（复用率高但角度差大）；
越细越接近 TDMA。

## 4. 风险与未决问题

| 风险 | 状态 | 缓解 |
|---|---|---|
| 只改编号、不改波束矢量 → 同组内仍指向某一个 UE | **已确认存在** | Level 1 先试；若增益损失太大再做 Level 2（指向 bin 中心）|
| 同组内角度差导致增益损失 | 取决于网格 | 8×8 阵列 HPBW ≈ 12.75°，15° 网格下最坏偏 7.5° ≈ −4.2 dB |
| `BeamId(0,0)` 与空编号冲突 | 已规避 | bin 编号从 1 开始 |
| `BeamChangeReport` 被触发导致 MAC 异常 | **未验证** | 阶段 A 第一步先查 `nr-gnb-mac.cc:1280` 的触发条件 |
| 改完偏离"用现成 5G-LENA" | 需在文档标注 | 明确写为"我们扩展的波束算法" |

## 5. 对历史结论的修正

**去重键修复后，容量数字与之前不同了**，需要说明：

| 口径 | 修复前（有 bug）| 修复后（本次）|
|---|---:|---:|
| OFDMA 调度字节 | 45.8 Mbps/cell | 41.64 MB / 0.6 s / 3 = **185 Mbps/cell** |
| TDMA 调度字节 | 91.5 Mbps/cell | 41.92 MB / 0.6 s / 3 = **186 Mbps/cell** |
| **OFDMA 交付率** | 未测 | **58.8%** |
| **TDMA 交付率** | 未测 | **89.2%** |

**关键修正**：修复去重键后，两者的**调度字节几乎相同**（185 vs 186 Mbps/cell），
但 **BLER 差 11 倍**（27.4% vs 2.4%）、**交付率差 30 个百分点**（58.8% vs 89.2%）。

**所以"OFDMA 吞吐只有一半"这个旧结论要改口径**：不是调度得少，而是
**调度出去的三分之一被损坏、靠 HARQ 重传补**，代价体现在交付率和时延上，不是调度字节上。

## 6. 阶段 A 的准入判据（请审核）

| 项 | 状态 |
|---|---|
| 根因是否已实证 | ✅ 是（1 个波束组、空编号、11 UE/符号、BLER 27.4%）|
| 修复点是否明确 | ✅ 是（只需改波束算法的编号生成）|
| 是否需改 PHY / 信道 | ✅ 否（这是 A 比 B 便宜的根本原因）|
| 主要未验证风险 | ⚠️ 同组角度差导致的增益损失、`BeamChangeReport` 副作用 |
| 建议 | **进入阶段 A Level 1**（只改编号，0.5 天）|

## 7. 复现命令

```bash
# OFDMA（复现 1 个波束组、11 UE/符号）
ns3.39-cttc-nr-traffic-3gpp-xr-optimized --trafficModel=paper --preset=paperTable3 \
  --scheme=conventional --numSectors=3 --numSites=1 --siteRings=0 --statsRings=0 \
  --uePerCell=12 --indoorRatio=0.8 --ueSpeedKmh=3 --tddPattern=DDDSU \
  --warmupMs=500 --appDuration=1000 --scheduler=ofdma-pf --rngRun=1

# TDMA 对照：把 --scheduler 换成 tdma-qos
```

输出：`ues_per_symbol.csv`（每符号 UE 数分布）、`mac_tb.csv`、`phy_tb.csv`、
`flowmon_center.csv`、`run.log` 里的 `[BEAMGRP]` 行。