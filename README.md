# EMT-Pytorch-ECCV2022 复现记录

本仓库是对 ECCV 2022 论文 **Efficient Meta-Tuning for Content-Aware Neural Video Delivery (EMT)** 的复现工作，包含环境搭建、数据准备、训练脚本适配、psnr_map 生成与本地实验记录。

- 原论文：*Efficient Meta-Tuning for Content-Aware Neural Video Delivery* (ECCV 2022)
- 官方实现：[Neural-video-delivery/EMT-Pytorch-ECCV2022](https://github.com/Neural-video-delivery/EMT-Pytorch-ECCV2022)
- 本仓库 Fork 自官方仓库，用于记录个人复现过程。

## 复现环境

| 项目 | 配置 |
|------|------|
| 操作系统 | WSL2 Ubuntu 24.04 |
| Python | 3.12.3 (venv) |
| PyTorch | 2.5.1+cu121 |
| GPU | NVIDIA GeForce RTX 4060 Laptop 8GB |
| CUDA | 12.1 |

依赖版本已锁定，可通过 `requirements-lock.txt` 安装：

```bash
pip install -r requirements-lock.txt
```

主要依赖版本：numpy 1.26.4、opencv-python 4.9.0.80、scikit-image 0.22.0、scipy 1.17.1、matplotlib 3.11.2、numba 0.68.0、tqdm 4.70.1、tensorboardX 2.6.5、h5py 3.16.0。

## 复现进度

- [x] 环境搭建（venv + PyTorch + CUDA）
- [x] DIV2K 训练集/验证集下载与解压
- [x] 从 HR 生成 x2 LR 图像（`generate_lr.py`）
- [x] 修改 `src/meta_learning.sh` 适配本地路径与 8GB 显存
- [x] 跑通 smoke test（`--epochs 2`，PSNR 22.877）
- [x] 完整元学习训练（50 epochs，最佳 PSNR 32.252 @epoch 46）
- [x] VSD4K 数据集下载与解压（`lol_15s_1`，495 帧 HR + X2 LR）
- [x] 生成 `lol_15s_1` 的 psnr_map（495 个文件，416941 个 patch 位置）
- [x] 元调优 smoke test（MG1 find_mask + grad_mask 跑通）
- [x] 元调优 MG1~MG4 链式微调（PSNR 优先采样）
- [x] 采样策略消融实验（均匀采样 vs PSNR 优先）
- [x] 多视频类别验证（sport / dance，MG1~MG4）
- [x] Meta-Tuning baseline 对比
- [ ] AdaFM baseline 对比（引用论文数值）
- [ ] Sidetuning baseline 对比（引用论文数值）
- [ ] 结果评估与论文对齐

## 元调优结果

以下元调优 PSNR 来自运行日志中标记为 `[DIV2K x2]` 的评估输出。`DIV2K` 是代码使用的数据集类名；元调优脚本将 `--dir_data` 指向各视频目录，因此这里的评估图像来自对应视频帧。每段训练与评估使用相同帧范围，故这些结果不是独立留出集指标。

### PSNR 优先采样（DIV2K_PSNR）完整结果

| 段 | 帧范围 | p_mask | find_mask PSNR | grad_mask PSNR |
|----|--------|--------|---------------|----------------|
| MG1 | 1-150 | 0.20 | 33.638 | 32.609 |
| MG2 | 151-300 | 0.01 | 33.607 | 32.640 |
| MG3 | 301-450 | 0.01 | 34.362 | 33.187 |
| MG4 | 451-495 | 0.01 | 33.841 | 32.794 |

**观察**：
- MG1~MG3 链式微调 PSNR 逐步提升，说明模型逐步适应了视频内容分布
- MG4 数据量仅 45 帧（约前段的 30%），PSNR 略有回退，符合预期
- MG1 使用较大 `p_mask=0.20` 进行粗粒度微调，MG2+ 使用 `p_mask=0.01` 精细微调

### 多视频类别验证（MG1~MG4）

sport 和 dance 均使用 495 帧视频数据、PSNR 优先采样及 2 epochs 微调。每段的 grad_mask 阶段以前一阶段的最佳模型为起点；MG1 从元学习模型开始。MG1~MG3 结果来自 `experiment/sport_run.log` 和 `experiment/dance_run.log`，MG4 结果来自 `experiment/sport_MG4_run.log` 和 `experiment/dance_MG4_run.log`。

| 类别 | 段 | 帧范围 | p_mask | find_mask PSNR | grad_mask PSNR |
|------|----|--------|--------|----------------|----------------|
| sport_15s_1 | MG1 | 1-150 | 0.20 | 44.433 | 43.383 |
| sport_15s_1 | MG2 | 151-300 | 0.01 | 45.562 | 44.410 |
| sport_15s_1 | MG3 | 301-450 | 0.01 | 44.098 | 42.708 |
| sport_15s_1 | MG4 | 451-495 | 0.01 | 44.723 | 43.454 |
| dance_15s_1 | MG1 | 1-150 | 0.20 | 40.574 | 37.875 |
| dance_15s_1 | MG2 | 151-300 | 0.01 | 40.001 | 37.288 |
| dance_15s_1 | MG3 | 301-450 | 0.01 | 39.505 | 36.899 |
| dance_15s_1 | MG4 | 451-495 | 0.01 | 39.886 | 37.287 |

这些结果是在对应视频帧上的阶段内评估值，但各阶段评估范围同时参与了调优，不能视为独立留出集结果，也不宜直接据此比较类别画质。MG4 只有 45 帧，指标稳定性有限。

### 采样策略消融实验（MG1~MG3）

| 段 | 帧范围 | p_mask | 采样方式 | find_mask PSNR | grad_mask PSNR |
|----|--------|--------|----------|---------------|----------------|
| MG1 | 1-150 | 0.20 | 均匀 (DIV2K) | 33.270 | 32.588 |
| MG1 | 1-150 | 0.20 | PSNR 优先 (DIV2K_PSNR) | 33.638 | 32.609 |
| MG2 | 151-300 | 0.01 | 均匀 (DIV2K) | 33.277 | 32.620 |
| MG2 | 151-300 | 0.01 | PSNR 优先 (DIV2K_PSNR) | 33.607 | 32.640 |
| MG3 | 301-450 | 0.01 | 均匀 (DIV2K) | 33.951 | 33.164 |
| MG3 | 301-450 | 0.01 | PSNR 优先 (DIV2K_PSNR) | 34.362 | 33.187 |

**grad_mask PSNR 提升汇总**：

| 段 | 均匀采样 | PSNR 优先采样 | Δ (PSNR优先 - 均匀) |
|----|----------|--------------|---------------------|
| MG1 | 32.588 | 32.609 | +0.021 |
| MG2 | 32.620 | 32.640 | +0.020 |
| MG3 | 33.164 | 33.187 | +0.023 |

**观察**：
- PSNR 优先采样在每段均优于均匀采样，grad_mask PSNR 提升约 **0.02 dB**
- 提升幅度虽然不大，但趋势一致，说明论文的采样机制在小规模实验下仍然有效
- 由于本复现仅使用 2 epochs 微调，与论文的完整训练设置存在差异，绝对数值仅供参考

## Baseline 对比（lol_15s_1）

### 本地复现结果

| 方法 | 类型 | 微调参数量 | MG1 | MG2 | MG3 | MG4 |
|------|------|-----------|-----|-----|-----|-----|
| **EMT (本复现)** | 梯度掩码微调 | 1%~20% | 32.609 | 32.640 | 33.187 | 32.794 |
| Meta-Tuning | 全模型微调 | 100% | 32.903 | 33.069 | 33.818 | 33.455 |

**观察**：
- Meta-Tuning 因微调全部参数，PSNR 略高于 EMT（约 +0.3 dB）
- EMT 的优势在于**效率**：只更新 1%~20% 参数，梯度掩码训练时间显著缩短
- 论文的核心 claim 是“高效元调优”，精度与效率的权衡是关键

### 效率对比（MG1，lol_15s_1）

| 方法 | 微调参数量 | 训练时间 | 相对加速 |
|------|-----------|---------|---------|
| Meta-Tuning | 100% | ~10s | 1× |
| **EMT (梯度掩码)** | 1%~20% | ~4s | **~2.5×** |

### 论文引用数值

以下数据引自 EMT 论文补充材料 Table 4（不同数据集上的 PSNR 对比）：

| 方法 | inter-45s | sport-45s | dance-45s |
|------|-----------|-----------|-----------|
| C₁₋ₙ (300 epochs, from scratch) | 38.95 | 46.03 | 43.47 |
| C*ₚ₁₋ₙ (800 epochs, pretrained) | 39.45 | 46.84 | 43.09 |
| **EMT (Ours)** | **39.56** | **46.41** | **44.59** |

**注意**：AdaFM 和 Sidetuning 在本论文中的具体 PSNR 数值未在补充材料中单独列出，建议查阅论文正文 Table 2/3 或相关引用获取。

## 目录结构

```
EMT-Pytorch-ECCV2022/
├── src/                              # 核心代码
│   ├── main.py                       # 训练入口
│   ├── option.py                     # 参数定义
│   ├── dataloader.py                 # 数据加载
│   ├── trainer_maml.py               # MAML 训练器
│   ├── trainer_gradmask.py           # 梯度掩码训练器
│   ├── generate_mask.py              # 梯度掩码生成
│   ├── meta_learning.sh              # 官方元学习脚本（保留）
│   ├── meta_learning_local.sh        # 本地元学习脚本（已适配）
│   ├── meta_tuning.sh                # 官方元调优脚本（保留）
│   ├── meta_tuning_local.sh          # 本地元调优脚本（MG1~MG3）
│   ├── meta_tuning_mg4.sh            # 本地元调优脚本（MG4）
│   ├── meta_tuning_sport.sh          # sport 类别元调优（MG1~MG3）
│   ├── meta_tuning_dance.sh          # dance 类别元调优（MG1~MG3）
│   ├── meta_tuning_uniform.sh        # 消融实验脚本（均匀采样）
│   ├── baseline_metatuning.sh        # Meta-Tuning baseline 脚本
│   └── ...
├── data/                             # 数据集（未纳入版本控制）
│   ├── DIV2K/
│   │   ├── DIV2K_train_HR/
│   │   ├── DIV2K_train_LR_bicubic/X2/
│   │   └── DIV2K_valid_HR/
│   └── VSD4K/
│       ├── lol_15s_1/
│       │   ├── DIV2K_train_HR/
│       │   ├── DIV2K_train_LR_bicubic/X2|X3|X4/
│       │   ├── psnr_map/             # 495 个 psnr_map 文件
│       │   ├── bin/                  # 训练缓存
│       │   └── video/
│       ├── sport_15s_1/              # 同结构，含独立 psnr_map
│       └── dance_15s_1/              # 同结构，含独立 psnr_map
├── experiment/                       # 训练输出（未纳入版本控制）
├── grad_mask/                        # 梯度掩码文件（未纳入版本控制）
├── generate_lr.py                    # 从 HR 生成 x2 LR 图像的脚本
├── requirements-lock.txt             # 锁定依赖
└── .gitignore
```

## 数据准备

### 1. DIV2K（元学习阶段）

下载 HR 图像并解压到 `data/DIV2K/`：

```
data/DIV2K/
├── DIV2K_train_HR/        # 0001.png ~ 0800.png
├── DIV2K_train_LR_bicubic/X2/   # 0001x2.png ~ 0800x2.png
└── DIV2K_valid_HR/        # 0801.png ~ 0900.png
```

生成 x2 LR 图像：

```bash
python generate_lr.py
```

执行后会在 `data/DIV2K/DIV2K_train_LR_bicubic/X2/` 下生成 `0001x2.png` ~ `0800x2.png`。

### 2. VSD4K（元调优阶段）

从 CaFM-Pytorch-ICCV2021 仓库获取 VSD4K 数据集，解压后放到 `data/VSD4K/`。

本复现使用 `game_15s_1.zip`（内含 `lol_15s_1` 目录，495 帧）：

```
data/VSD4K/lol_15s_1/
├── DIV2K_train_HR/                    # 00001.png ~ 00495.png
├── DIV2K_train_LR_bicubic/
│   ├── X2/                            # 00001x2.png ~ 00495x2.png
│   ├── X3/
│   └── X4/
├── psnr_map/                          # 由 test_pn() 生成
└── video/
    └── lol_15s_1080p_fps30_bv10.mp4
```

### 3. 生成 psnr_map

`psnr_map` 是 PSNR 优先采样的必需文件，用于记录每帧每个 patch 位置的 PSNR 排序。

**生成方式**：在 `trainer_maml.py` 的 `I_frames` 字典中添加 `'lol_15s_1': list(range(1, 496))`，然后通过 `--patchnet_test` 触发 `test_pn()`：

```bash
cd src
CUDA_VISIBLE_DEVICES=0 python main.py \
  --model espcn --scale 2 --patch_size 144 --batch_size 8 \
  --maml \
  --save /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/tmp_gen_psnr_map \
  --pre_train /path/to/metaLearned.pt \
  --reset --data_train DIV2K --data_test DIV2K \
  --data_range 1-495/1-495 --is45s \
  --dir_data /path/to/data/VSD4K/lol_15s_1 \
  --patchnet_test --test_only \
  --dir_mask /path/to/grad_mask/tmp.pt
```

生成完毕后 `data/VSD4K/lol_15s_1/psnr_map/` 下应有 495 个 `.pt` 文件，每个文件内容是 shape 为 `(N, 3)` 的数组 `[iy, ix, psnr]`。

## 快速开始

### 1. 激活虚拟环境

```bash
cd ~/code/EMT-Pytorch-ECCV2022
source emt-env/bin/activate
```

### 2. 元学习训练

```bash
bash src/meta_learning_local.sh
```

### 3. 元调优（MG1~MG3）

```bash
mkdir -p grad_mask
bash src/meta_tuning_local.sh
```

### 4. 元调优（MG4）

```bash
bash src/meta_tuning_mg4.sh
```

### 5. 采样策略消融实验

```bash
bash src/meta_tuning_uniform.sh 2>&1 | tee experiment/uniform_run.log
```

### 6. sport / dance 多视频类别元调优

sport 和 dance 数据目录分别为 `data/VSD4K/sport_15s_1/` 与 `data/VSD4K/dance_15s_1/`。每个目录需要包含 495 张 HR、对应的 X2 LR 帧，以及各自独立的 `psnr_map/`。`trainer_maml.py` 中的 `I_frames` 已为这两个数据集配置 1~495 帧。

生成 dance 的 `psnr_map`（sport 已按相同流程生成）：

```bash
cd src
CUDA_VISIBLE_DEVICES=0 python main.py \
  --model espcn --scale 2 --patch_size 144 --batch_size 8 \
  --maml \
  --save ../experiment/tmp_gen_psnr_dance \
  --pre_train ../experiment/experiment/local_maml_espcn_x2_p144_b8_e50/model/46/model_best.pt \
  --reset --data_train DIV2K --data_test DIV2K \
  --data_range 1-495/1-495 --is45s \
  --dir_data ../data/VSD4K/dance_15s_1 \
  --patchnet_test --test_only \
  --dir_mask ../grad_mask/tmp_dance.pt
cd ..
```

确认 `data/VSD4K/dance_15s_1/psnr_map/` 下有 495 个 `_psnr_map.pt` 文件后，运行对应类别脚本：

```bash
bash src/meta_tuning_sport.sh 2>&1 | tee experiment/sport_run.log
bash src/meta_tuning_dance.sh 2>&1 | tee experiment/dance_run.log
```

两份脚本分别使用独立的输出目录和梯度 mask，运行 MG1~MG3。随后 MG4 从对应类别的 MG3 最佳模型继续，帧范围为 `451-495/451-495`；本次实验结果见上表。

### 7. Baseline 对比

运行 Meta-Tuning 全模型微调 baseline：

```bash
bash src/baseline_metatuning.sh 2>&1 | tee experiment/baseline_metatuning_full.log
```

## 对官方代码的修改

### 1. `src/trainer_maml.py`

**`I_frames` 字典**：新增 `lol_15s_1`、`sport_15s_1` 和 `dance_15s_1` 的 1~495 帧配置，使 `test_pn()` 能识别这些数据集并生成 `psnr_map`。

### 2. `src/meta_learning_local.sh`

本地元学习脚本，基于官方 `meta_learning.sh` 修改：

- `--dir_data` 指向本地 `data/DIV2K`
- `--batch_size 8`（适配 8GB 显存）
- `--epochs 50`，`--decay 30-45`
- `--save` 指向 `experiment/local_maml_espcn_x2_p144_b8_e50`
- 脚本开头加 `cd "$(dirname "$0")"`，确保任意目录运行都能找到 `main.py`

**训练结果**：50 epochs，最佳 PSNR 32.252 @epoch 46。

### 3. `src/meta_tuning_local.sh`

本地元调优脚本，MG1~MG4 链式微调，每段 find_mask + grad_mask：

- `--pre_train` 分别指向元学习模型（MG1）与上一段最佳模型（MG2~MG4）
- `--data_range` 按 150 帧一段划分
- `--data_train DIV2K_PSNR`（使用 PSNR 优先采样）
- `--p_mask 0.20`（MG1）/ `0.01`（MG2~MG4）
- `--dir_mask` 指向 `grad_mask/mask_lol.pt`

### 4. `src/meta_tuning_mg4.sh`

MG4 补充脚本，参数与 MG2/MG3 一致，仅 `--data_range 451-495/451-495`，`--pre_train` 指向 MG3。

### 5. `src/meta_tuning_uniform.sh`

采样策略消融实验脚本，用 `--data_train DIV2K`（均匀采样）跑 MG1~MG3，与 `DIV2K_PSNR` 版本对比。输出目录后缀为 `_uniform`，mask 文件独立保存。

### 6. `generate_lr.py`

新增脚本，用于从 HR 图像生成 x2 LR 图像，避免下载官方 LR 压缩包：

- 读取 `DIV2K_train_HR/*.png`
- 使用 bicubic 下采样 2 倍
- 保存为 `DIV2K_train_LR_bicubic/X2/{name}x2.png`

### 7. `src/meta_tuning_sport.sh` 和 `src/meta_tuning_dance.sh`

多视频类别元调优脚本，分别针对 sport 和 dance 运行 MG1~MG3，使用独立的 `psnr_map`、梯度 mask 和实验输出目录，避免覆盖 `lol_15s_1` 或其他类别的结果。

### 8. `src/main.py`

- 简化 Trainer 选择逻辑：`find_mask`/`grad_mask` 使用 `Trainer_gradmask`，其余使用 `Trainer_maml`
- 修复训练循环缩进，确保所有分支都进入 `while not t.terminate()` 循环

### 9. `src/option.py`

- 删除重复的 `--adafm` 参数定义，避免参数重复注册

### 10. `src/baseline_metatuning.sh`

Meta-Tuning baseline 脚本，使用全模型微调，与 EMT 的梯度掩码微调结果进行对比。

## 已知问题与注意事项

### 1. `psnr_map` 生成需手动触发

`--data_train DIV2K_PSNR` 依赖 `--dir_data/psnr_map/{filename}_psnr_map.pt` 文件。生成逻辑位于 `trainer_maml.py` 的 `test_pn()` 方法，需通过 `--patchnet_test` 参数显式触发。`--test_only` 走的是 `test()` 而非 `test_pn()`，因此必须加上 `--patchnet_test`。

### 2. `is45s` 硬编码分段

`--is45s` 在 `trainer_maml.py` 和 `trainer_gradmask.py` 中硬编码了 150 帧一段的分段逻辑：

```
1-150    → flag 0 (MG1)
151-300  → flag 1 (MG2)
301-450  → flag 2 (MG3)
451-600  → flag 3 (MG4)
...
```

`lol_15s_1` 只有 495 帧，MG4 仅覆盖 45 帧（451-495），数据量不足以获得稳定指标。

### 3. `percentage` 输出的舍入行为

`generate_mask.py` 中：

```python
idx = int(len(dist_mean[0]) * p_mask)
pctg = idx / len(dist_mean[0]) * 100
```

`pctg` 是实际选中的元素比例，由于 `int()` 向下取整，当 `p_mask=0.01` 时输出约 0.9987%（而非精确 1%）。这是正常的舍入行为，不是 bug。

### 4. `--reset` 参数

会删除同名输出目录，正式训练前请更换 `--save` 名称或移除该选项。

### 5. WSL 路径干扰

WSL 默认会把 Windows 的 anaconda 路径追加到 Linux PATH，可能导致 CMake / pip 找到错误的库。建议在新终端中执行：

```bash
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -vi anaconda | paste -sd:)
```

### 6. 双层 experiment 目录

由于 `--save` 使用绝对路径，输出会落在 `experiment/experiment/` 下（代码内部又拼了一层 `experiment/`）。不影响使用，只是路径略长。

### 7. PSNR 日志未持久化

当前脚本的 PSNR 输出直接打印到终端，未写入 log 文件。如需保存，可改用：

```bash
bash src/meta_tuning_mg4.sh 2>&1 | tee experiment/local_tuning_lol_MG4/run.log
```

## 后续计划

1. **AdaFM / Sidetuning 对比**：查阅论文正文 Table 2/3，摘录对应 PSNR 数值，填入对比表
2. **SSIM / LPIPS 指标**：补充结构相似性和感知指标
3. **vlog 扩展**：补充更多视频类别的验证
4. **ns-3 仿真环境**：为后续 RTSR (WCNC 2023) 复现搭建 5G-Advanced 网络仿真平台

## 参考

- 论文：[ECCV 2022] Efficient Meta-Tuning for Content-Aware Neural Video Delivery
- 官方代码：https://github.com/Neural-video-delivery/EMT-Pytorch-ECCV2022
- DIV2K 数据集：https://data.vision.ee.ethz.ch/cvl/DIV2K/
- VSD4K 数据集（用于元调优）：可从 [CaFM-Pytorch-ICCV2021](https://github.com/Neural-video-delivery/CaFM-Pytorch-ICCV2021) 仓库获取
- RTSR 论文：[WCNC 2023] Real-Time Super-Resolution: A New Mechanism for XR over 5G-Advanced

## 许可

本仓库仅用于学术复现与学习，代码版权归原作者所有。