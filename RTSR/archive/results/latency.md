# 实时性实测（论文标题里的 Real-Time 到底能不能达到）

设备：RTX 4060 Laptop（8 GB），PyTorch 2.5.1+cu121，FP32、eager 模式，batch=1。
脚本：`algorithm/tools/bench_latency.py`（30 次迭代取均值，5 次预热，`torch.cuda.synchronize`）。

## 结果

### 540p → 1080p（lol 片段实验）

| 模型 | 尺寸 | 单帧时延 | 吞吐 | 显存峰值 | 30 FPS 预算 33.3 ms | 60 FPS 预算 16.7 ms |
|---|---:|---:|---:|---:|---|---|
| M1 | 62.6 KB | **20.6 ms** | 48.5 FPS | 186 MiB | ✅ | ❌ |
| M2 | 506.9 KB | 52.8 ms | 18.9 FPS | 522 MiB | ❌ | ❌ |
| M3 | 5351 KB | 231.0 ms | 4.3 FPS | 1277 MiB | ❌ | ❌ |

### 1080p → 2160p（论文设置）

| 模型 | 尺寸 | 单帧时延 | 吞吐 | 显存峰值 | 30 FPS | 60 FPS |
|---|---:|---:|---:|---:|---|---|
| M1 | 62.6 KB | **91.9 ms** | 10.9 FPS | 738 MiB | ❌ | ❌ |
| M2 | 506.9 KB | 218.6 ms | 4.6 FPS | 2082 MiB | ❌ | ❌ |
| M3 | 5351 KB | 953.5 ms | 1.0 FPS | 5094 MiB | ❌ | ❌ |

## 三条结论

1. **"实时"在纯 PyTorch FP32 下不成立**：论文的 30–120 FPS 场景里，只有 M1 在 540p→1080p
   时勉强到 48.5 FPS；一旦到论文的 2160p 输出，最好的 M1 也只有 10.9 FPS。
2. **时延与模型尺寸近似线性**：62.6 KB → 20.6 ms、507 KB → 52.8 ms、5351 KB → 231 ms（1080p 输出），
   即每 10 倍参数量约 4.4 倍时延 —— 与 EDSR 的计算量（∝ 特征数² × 块数）一致。
3. **显存是另一个约束**：M3 在 2160p 下峰值 5.1 GB，8 GB 笔记本 GPU 上已接近上限。

## 与论文的差距怎么解释

论文没有给出推理时延的实测值，只给了模型尺寸与 PSNR（Table I）。要做到论文说的
"real-time"，通常还需要：TensorRT/OpenVINO 图优化、FP16/INT8 量化、算子融合、
或更强的端侧 NPU。**本复现的时延是一个"未优化的上界"**，应作为工程约束记录，而不是
否定论文的实时性主张。

## 复现命令

```bash
PY=~/code/EMT-Pytorch-ECCV2022/emt-env/bin/python
$PY tools/bench_latency.py --exp ../experiment_rtsr_m2_26feats --blocks 8 --feats 26 --lr 960 540
$PY tools/bench_latency.py --exp ../experiment_t2_4k_b5000  --blocks 8 --feats 26 --lr 1920 1080
```