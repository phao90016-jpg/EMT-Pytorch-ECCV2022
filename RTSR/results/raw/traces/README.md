# 仿真运行记录与 trace

一次完整的小规模仿真（3 个 UE，100 MHz，20 s）的运行日志和 FlowMonitor trace，
用来展示"仿真跑出来到底长什么样"，也是所有流量/时延数字的原始来源。

## 文件

| 文件 | 内容 |
|---|---|
| `rtsr-run.log` | 仿真控制台完整输出（ping 预热 + 14 条流的统计 + 汇总） |
| `rtsr-flowmon.xml` | FlowMonitor trace：每流计数器、**每包时延直方图**、流分类表 |

## 怎么生成的

```bash
cd ~/code/ns-allinone-3.39/ns-3.39
./ns3 run "cttc-nr-traffic-3gpp-xr --arUeNum=1 --vrUeNum=1 --cgUeNum=1 \
--bandwidth=100e6 --numerology=1 --appDuration=20000"
```

`rtsr-simulation.cc` 里新增了：

```cpp
flowmonHelper.SerializeToXmlFile("rtsr-flowmon.xml", true, true);
```

第三个参数 `true` 打开直方图，这是拿到"每包时延分布"的关键——控制台只打印均值。

## 这次运行的结构（14 条流）

| 流 | 目的端口 | 类型 | 说明 |
|---|---|---|---|
| 1–3 | 1121–1123 | AR 视频 | 3 条子流（pose/视频/音频） |
| 4 | 1131 | VR 视频 | |
| 5 | 1141 | CG 视频 | |
| 6–14 | 5000 | SR 模型 | 3 UE × 3 次更新，**每次更新是一条独立流** |

> 注意：SR 模型每次 `SendSrModel` 都新建一个 `UdpClient`，所以 FlowMonitor 里
> **一次模型更新 = 一条流**，不是一条持续流。这也是流量账要按"发送量 ÷ 单次大小"
> 反推更新次数的原因。

## 结果（`python3 analyze_trace.py results/raw/traces/rtsr-flowmon.xml`）

```
=== aggregate by class (PDB = 10 ms) ===
SR model  tx=  4770 pkts  delivery= 92.5%  delay>PDB= 76.4%  bytes=   4.79 MB
XR video  tx= 13326 pkts  delivery=100.0%  delay>PDB=  0.0%  bytes=  37.61 MB
```

- 视频：**100% 投递、平均 1.6 ms、没有一个包超过 10 ms PDB**；
- 模型：92.5% 投递、平均 17–24 ms、**76% 的包超过 10 ms PDB**。

这就是"分层 QoS"的直接证据：同一条链路、同一时刻，视频稳在 PDB 内，
模型流承担了全部时延和丢包。

## XML 结构

```xml
<FlowMonitor>
  <FlowStats>
    <Flow flowId="1" txBytes="627200" rxBytes="627200"
          txPackets="4900" rxPackets="4900" lostPackets="0"
          delaySum="+8.23e+09ns" jitterSum="+5.85e+07ns">
      <delayHistogram nBins="...">
        <bin index="16" start="0.0016" width="0.0001" count="4715" />
        ...
      </delayHistogram>
      <jitterHistogram>...</jitterHistogram>
      <packetSizeHistogram>...</packetSizeHistogram>
    </Flow>
  </FlowStats>
  <Ipv4FlowClassifier>
    <Flow flowId="1" sourcePort="49153" destinationPort="1121" ... />
  </Ipv4FlowClassifier>
  <FlowProbes>
    <FlowProbe index="0">...</FlowProbe>
  </FlowProbes>
</FlowMonitor>
```

**三个直方图的单位不同**，解析时必须分开取：

| 直方图 | 单位 | 用途 |
|---|---|---|
| `delayHistogram` | 秒（bin 宽 0.1 ms） | 算 PDB 超限比例 ← 我们用的 |
| `jitterHistogram` | 秒（bin 宽 1 ms） | 抖动分布 |
| `packetSizeHistogram` | 字节（bin 宽 20 B） | 包长分布 |

`analyze_trace.py` 只取 `delayHistogram`；混用会把"包长 120 字节"当成"时延 120 秒"，
得出荒谬的 PDB 超限率（我第一次就踩了这个坑）。

## 与论文 FSR 的关系

这份 trace 给出的是**包级**的 `delay > PDB` 比例，比控制台的均值更接近论文的帧成功率，
但仍不等价：

- 论文 FSR 是**帧级**：一帧被切成多个包，整帧在 BS 缓冲等待 ≤ 10 ms 才算成功；
- 包里没有帧号（5G-LENA 的 XR 头被注释掉了），要重建帧必须按 burst 边界聚合。

所以这份数据能支撑"包级 PDB 满足率"，帧级 FSR 还需要一个 burst 聚合的 sink。
