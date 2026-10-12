# EMT-Pytorch-ECCV2022 复现记录

本仓库是对 ECCV 2022 论文 **Efficient Meta-Tuning for Content-Aware Neural Video Delivery (EMT)** 的复现工作，包含环境搭建、数据准备、训练脚本适配与本地实验记录。

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

`requirements-lock.txt` 锁定了当前的主要依赖版本，可通过以下命令安装：

```bash
pip install -r requirements-lock.txt
```

注意：训练还依赖 `numba`、`tqdm`、`tensorboardX` 和 `h5py`，目前这些包尚未全部列入锁文件；在新环境中运行前，请根据需要安装并确认版本。

主要依赖版本：
- numpy 1.26.4
- opencv-python 4.9.0.80
- scikit-image 0.22.0
- scipy 1.17.1
- matplotlib 3.11.2
- numba 0.68.0
- tqdm 4.70.1
- tensorboardX 2.6.5
- h5py 3.16.0

## 复现进度

- [x] 环境搭建（venv + PyTorch + CUDA）
- [x] DIV2K 训练集/验证集下载与解压
- [x] 从 HR 生成 x2 LR 图像（`generate_lr.py`）
- [x] 本地元学习脚本适配路径与 8GB 显存
- [x] 元学习 smoke test（`--epochs 2`，PSNR 22.877）
- [x] 完整元学习训练（50 epochs，最佳 PSNR 32.252 @epoch 46）
- [x] VSD4K 数据集下载与解压（`lol_15s_1`，495 帧 HR + X2 LR）
- [x] 元调优 smoke test（MG1 的 `find_mask` + `grad_mask` 跑通）
- [ ] 元调优完整流程（MG1~MG4 多段）
- [ ] 生成 `psnr_map`，运行论文原版 `DIV2K_PSNR` 采样流程
- [ ] 结果评估与对比

## 目录结构

```text
EMT-Pytorch-ECCV2022/
├── src/                              # 核心代码
│   ├── main.py                       # 训练入口
│   ├── option.py                     # 参数定义
│   ├── dataloader.py                 # 数据加载
│   ├── trainer_maml.py               # MAML 训练器
│   ├── trainer_gradmask.py           # 梯度掩码训练器
│   ├── meta_learning.sh              # 官方元学习脚本（保留）
│   ├── meta_learning_local.sh        # 本地元学习脚本
│   ├── meta_tuning.sh                # 官方元调优脚本（保留）
│   ├── meta_tuning_local.sh          # 本地元调优脚本
│   └── ...
├── data/                             # 数据集（未纳入版本控制）
│   ├── DIV2K/
│   │   ├── DIV2K_train_HR/
│   │   ├── DIV2K_train_LR_bicubic/X2/
│   │   └── DIV2K_valid_HR/
│   └── VSD4K/
│       └── lol_15s_1/
│           ├── DIV2K_train_HR/
│           ├── DIV2K_train_LR_bicubic/X2|X3|X4/
│           └── video/
├── experiment/                       # 训练输出（未纳入版本控制）
├── grad_mask/                        # 梯度掩码文件（未纳入版本控制）
├── generate_lr.py                    # 从 HR 生成 x2 LR 图像的脚本
├── requirements-lock.txt             # 锁定依赖
└── .gitignore
```

## 数据准备

### 1. DIV2K（元学习阶段）

下载 DIV2K HR 图像并解压到 `data/DIV2K/`：

```text
data/DIV2K/
├── DIV2K_train_HR/        # 0001.png ~ 0800.png
└── DIV2K_valid_HR/        # 0801.png ~ 0900.png
```

生成 x2 LR 图像：

```bash
python generate_lr.py
```

执行后会在 `data/DIV2K/DIV2K_train_LR_bicubic/X2/` 下生成 `0001x2.png` ~ `0800x2.png`。该脚本使用 Pillow bicubic 缩放；若要严格复现官方评测结果，应使用官方 LR 数据或确认缩放实现与评测设置一致。

### 2. VSD4K（元调优阶段）

从 CaFM-Pytorch-ICCV2021 仓库获取 VSD4K 数据集，解压后放到 `data/VSD4K/`。

本复现使用 `game_15s_1.zip`（内含 `lol_15s_1` 目录，495 帧），解压后的数据结构如下：

```text
data/VSD4K/lol_15s_1/
├── DIV2K_train_HR/                    # 00001.png ~ 00495.png
├── DIV2K_train_LR_bicubic/
│   ├── X2/                            # 00001x2.png ~ 00495x2.png
│   ├── X3/
│   └── X4/
└── video/
    └── lol_15s_1080p_fps30_bv10.mp4
```

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

### 3. 元调优

```bash
mkdir -p grad_mask
bash src/meta_tuning_local.sh
```

本地脚本中的数据、预训练权重和输出路径按当前工作环境配置；若仓库路径或数据位置不同，请先修改 `src/meta_learning_local.sh` 和 `src/meta_tuning_local.sh` 中对应的绝对路径。元调优脚本当前对 MG1 执行 `find_mask` 和 `grad_mask` smoke test（各 2 epochs）。

## 对官方代码的修改

### 1. `src/meta_learning_local.sh`

本地元学习脚本基于官方 `meta_learning.sh` 修改：

- `--dir_data` 指向本地 `data/DIV2K`
- `--batch_size 8`，适配 8GB 显存
- `--epochs 50`，`--decay 30-45`
- `--save` 指向本地实验目录 `local_maml_espcn_x2_p144_b8_e50`
- 脚本开头切换到脚本所在目录，确保从其他目录运行时也能找到 `main.py`

**训练结果**：50 epochs，最佳 PSNR 32.252 @epoch 46。

### 2. `src/meta_tuning_local.sh`

本地元调优脚本基于官方 `meta_tuning.sh` 修改，分为 `find_mask` 和 `grad_mask` 两步：

- `--pre_train` 加载元学习最佳权重（epoch 46）
- `--dir_data` 指向 `data/VSD4K/lol_15s_1`
- `--data_range 1-150/1-150`，对应 `is45s` 分段逻辑的 MG1
- `--data_train DIV2K`，绕过 `DIV2K_PSNR` 对 `psnr_map` 的依赖
- `--batch_size 8`
- `--p_mask 0.20`
- `--dir_mask` 指向 `grad_mask/mask_lol.pt`

**Smoke test 结果**：
- `find_mask`：生成梯度掩码（筛选 20% 参数）
- `grad_mask`：加载掩码微调，PSNR 32.588

### 3. `generate_lr.py`

新增脚本，用于从 HR 图像生成 x2 LR 图像，避免下载官方 LR 压缩包：

- 读取 `DIV2K_train_HR/*.png`
- 使用 Pillow bicubic 下采样 2 倍
- 保存为 `DIV2K_train_LR_bicubic/X2/{name}x2.png`

## 已知问题与注意事项

### 1. `psnr_map` 依赖

`--data_train DIV2K_PSNR` 需要在 `--dir_data/psnr_map/` 下预先生成 `{filename}_psnr_map.pt` 文件。生成逻辑在 `trainer_maml.py` 中，但受硬编码的 `I_frames` 字典限制，只对原作者的数据集生效。

**当前解决方案**：元调优脚本使用 `--data_train DIV2K` 绕过此依赖。代价是无法使用论文的 PSNR 优先采样机制，采样退化为均匀采样。完整的 `psnr_map` 生成流程待补充。

### 2. `is45s` 硬编码分段

`--is45s` 在 `trainer_maml.py` 和 `trainer_gradmask.py` 中按每 150 帧一段处理：

```text
1-150    → flag 0 (MG1)
151-300  → flag 1 (MG2)
301-450  → flag 2 (MG3)
451-600  → flag 3 (MG4)
...
```

本复现的 `lol_15s_1` 只有 495 帧，可支持 MG1~MG3，MG4 只有 45 帧。目前只跑通了 MG1。

### 3. `--reset` 参数

该参数会删除同名输出目录。正式训练前请更换 `--save` 名称或移除该选项。

### 4. WSL 路径干扰

WSL 可能会将 Windows Anaconda 路径追加到 Linux `PATH`，导致 CMake 或 pip 找到错误的库。若遇到相关问题，请检查 `PATH` 并移除冲突路径。

### 5. 双层 `experiment` 目录

由于 `--save` 使用绝对路径，而代码内部又拼接了一层 `experiment/`，输出可能位于 `experiment/experiment/` 下。不影响使用，但路径较长。

## 后续计划

1. 扩展元调优至 MG1~MG3 多段
2. 编写 `psnr_map` 生成脚本，运行论文原版 `DIV2K_PSNR` 流程
3. 完整复现论文的 PSNR/SSIM 指标
4. 整理复现报告

## 参考

- 论文：[ECCV 2022] Efficient Meta-Tuning for Content-Aware Neural Video Delivery
- 官方代码：https://github.com/Neural-video-delivery/EMT-Pytorch-ECCV2022
- DIV2K 数据集：https://data.vision.ee.ethz.ch/cvl/DIV2K/
- VSD4K 数据集（用于元调优）：可从 [CaFM-Pytorch-ICCV2021](https://github.com/Neural-video-delivery/CaFM-Pytorch-ICCV2021) 仓库获取

## 许可

本仓库仅用于学术复现与学习，代码版权归原作者所有。
