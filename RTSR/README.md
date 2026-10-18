# RTSR 网络层复现记录

本目录记录 WCNC 2023 论文《Real-Time Super-Resolution: A New Mechanism for XR over 5G-Advanced》的网络层（Network Layer）复现工作。当前仿真的重点是验证 5G-Advanced 网络中的**分层 QoS 传输机制（hierarchical QoS transport）**：在无线资源受限并发生拥塞时，优先保障 XR 视频流，并让低优先级的超分辨率（Super-Resolution, SR）模型更新流承担更多丢包。

## 仿真环境与前置条件

- **操作系统：** WSL2 Ubuntu
- **仿真工具：** ns-3.39 与 5G-LENA v2.5
- **核心代码：** [`rtsr-simulation.cc`](rtsr-simulation.cc)，基于 5G-LENA 示例 `cttc-nr-traffic-3gpp-xr.cc` 修改

运行前需准备好 ns-3.39 和 5G-LENA v2.5 的集成源码树，并满足其构建依赖。下文示例假设 NR 模块位于 ns-3 源码树的 `contrib/nr/` 目录。

## 核心代码修改

- **双流架构（dual-stream architecture）：** 在 XR 视频流（LD video stream）的基础上，增加周期性 SR 模型流；每次发送 530 KiB，每 6 秒发送一次。
- **分层 QoS 映射（hierarchical QoS mapping）：** XR 视频流映射到 `NGBR_LOW_LAT_EMBB`（高优先级承载）；SR 模型流映射到 `NGBR_VIDEO_TCP_DEFAULT`（低优先级承载）。
- **拥塞环境模拟（congestion setup）：** 系统带宽限制为 5 MHz，并将 `LteRlcUm::MaxTxBufferSize` 设为 500 KiB，以形成受限缓存下的队列拥塞和丢包条件。
- **QoS 调度器（QoS scheduler）：** 启用 `NrMacSchedulerTdmaQos`，配置 QoS 感知的逻辑信道调度算法，使高优先级承载在资源竞争时优先获得调度机会。

## 仿真结果与核心结论

以下为 60 秒仿真在 5 MHz 带宽、500 KiB RLC 缓冲区条件下记录的结果：

| 流类型 | 发送包数 | 接收包数 | 接收率 | 平均时延 | 说明 |
| :--- | ---: | ---: | ---: | ---: | :--- |
| **XR 视频流（高优先级）** | 3576 | 3500 | 97.9% | 451 ms | 丢包率较低，接收表现基本稳定 |
| **SR 模型流（低优先级）** | 530 | 476 | 89.8% | 668 ms | 约 10% 丢包，平均时延较高 |

**核心结论：** 在本次受限带宽与有限 RLC 缓冲区的测试条件下，低优先级 SR 流承担了更多丢包（约 10%），而高优先级 XR 视频流保持了 97% 以上的接收率。这与 RTSR 按网络状况自适应丢弃模型更新、为视频传输节省带宽的设计目标一致。该结果是特定拓扑、流量和仿真参数下的观测，不代表所有网络条件下都能绝对避免视频卡顿。

## 如何运行

将 `NS3_DIR` 修改为本机 ns-3.39 与 5G-LENA v2.5 集成源码树的路径，并从本仓库根目录执行：

```bash
set -euo pipefail

NS3_DIR="/path/to/ns-3.39"
SOURCE_FILE="$(pwd)/RTSR/rtsr-simulation.cc"
TARGET_FILE="$NS3_DIR/contrib/nr/examples/cttc-nr-traffic-3gpp-xr.cc"

test -f "$SOURCE_FILE"
test -f "$NS3_DIR/ns3"
test -f "$TARGET_FILE"

cp "$SOURCE_FILE" "$TARGET_FILE"
cd "$NS3_DIR"

./ns3 configure --enable-examples
./ns3 build
./ns3 run cttc-nr-traffic-3gpp-xr
```

## 下一步计划

- [ ] 使用 FlowMonitor 定量计算流量节省比例
- [ ] 使用 PyTorch 训练并导出 RTSR 所需的轻量级 EDSR 模型
- [ ] 开展算法层与网络层联合验证
