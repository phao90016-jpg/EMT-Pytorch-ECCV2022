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

`requirements-lock.txt` 记录了主要环境依赖版本，可通过以下命令安装：

```bash
pip install -r requirements-lock.txt
```

当前运行环境中还安装了训练所需的 `numba 0.68.0`、`tqdm 4.70.1`、`tensorboardX 2.6.5` 和 `h5py 3.16.0`。这些包目前未全部列入 `requirements-lock.txt`，新环境安装后应检查并补齐训练依赖。

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
- [x] 修改 `src/meta_learning.sh` 适配本地路径与 8GB 显存
- [x] 跑通 smoke test（`--epochs 2`，`--batch_size 8`，日志 PSNR 22.877）
- [ ] 完整元学习训练（800 epochs）
- [ ] 元调优阶段（需 VSD4K 数据）
- [ ] 梯度掩码分析与结果评估

## 目录结构

```text
EMT-Pytorch-ECCV2022/
├── src/                    # 核心代码
│   ├── main.py             # 训练入口
│   ├── option.py           # 参数定义
│   ├── dataloader.py       # 数据加载
│   ├── trainer_maml.py     # MAML 训练器
│   ├── trainer_gradmask.py # 梯度掩码训练器
│   ├── meta_learning.sh    # 元学习脚本（已适配本地路径）
│   ├── meta_tuning.sh      # 元调优脚本（待适配）
│   └── ...
├── data/                   # 数据集（未纳入版本控制）
│   └── DIV2K/
│       ├── DIV2K_train_HR/
│       ├── DIV2K_train_LR_bicubic/X2/
│       └── DIV2K_valid_HR/
├── experiment/             # 训练输出（未纳入版本控制）
├── generate_lr.py          # 从 HR 生成 x2 LR 图像的脚本
├── requirements-lock.txt   # 锁定依赖
└── .gitignore
```

## 数据准备

1. 下载 DIV2K 数据集（HR 图像）：
   - 训练集：`DIV2K_train_HR.zip`
   - 验证集：`DIV2K_valid_HR.zip`

2. 解压到 `data/DIV2K/`，目录结构如下：
   ```text
   data/DIV2K/
   ├── DIV2K_train_HR/        # 0001.png ~ 0800.png
   └── DIV2K_valid_HR/        # 0801.png ~ 0900.png
   ```

3. 生成 x2 LR 图像：
   ```bash
   python generate_lr.py
   ```
   执行后会在 `data/DIV2K/DIV2K_train_LR_bicubic/X2/` 下生成 `0001x2.png` ~ `0800x2.png`。此脚本使用 Pillow bicubic 缩放；若要严格复现官方评测结果，应使用官方 LR 数据或确认缩放实现与评测设置一致。

## 快速开始

1. 激活虚拟环境：
   ```bash
   cd ~/code/EMT-Pytorch-ECCV2022
   source emt-env/bin/activate
   ```

2. 运行 smoke test（2 epochs，batch size 8）：
   ```bash
   bash src/meta_learning.sh
   ```

3. 查看输出：
   - 模型权重保存在 `experiment/local_maml_espcn_x2_p144_b8_smoke_e2/`
   - 终端会打印每轮 PSNR

## 对官方代码的修改

### 1. `src/meta_learning.sh`

为适配本地路径与 8GB 显存，做了以下修改：
- `--dir_data` 指向本地 `data/DIV2K`
- `--batch_size` 从 `240` 改为 `8`
- `--epochs` 从 `800` 改为 `2`（smoke test 用）
- `--save` 使用本地 smoke test 实验名
- 脚本会先切换到 `src/` 再启动，确保相对路径正确

### 2. `generate_lr.py`

新增脚本，用于从 HR 图像生成 x2 LR 图像，避免下载官方 LR 压缩包：
- 读取 `DIV2K_train_HR/*.png`
- 使用 bicubic 下采样 2 倍
- 保存为 `DIV2K_train_LR_bicubic/X2/{name}x2.png`

### 3. `src/meta_learning_local.sh`
本地复现脚本，基于官方 `meta_learning.sh` 修改：
- `--dir_data` 指向本地 `data/DIV2K`
- `--batch_size 8`（适配 8GB 显存）
- `--epochs 50`，`--decay 30-45`
- `--save` 指向 `experiment/local_maml_espcn_x2_p144_b8_e50`
- 脚本开头加 `cd "$(dirname "$0")"`，确保任意目录运行都能找到 `main.py`

## 已知问题与注意事项

- **验证集读取**：当前代码在测试时仍读取 `DIV2K_train_HR` 的尾部数据，未使用 `DIV2K_valid_HR`。本次 smoke test 使用 `data_range 1-750/751-800`，测试范围是训练目录中的图像。若需评估真正的 DIV2K 验证集，需要调整 `src/data/div2k.py`。
- **`--reset` 参数**：会删除同名输出目录，正式训练前请更换 `--save` 名称或移除该选项。
- **`--decay 400-650`**：在 2-epoch smoke test 中不会触发学习率衰减。
- **训练依赖**：`utility.py` 需要 `numba`。当前环境已安装，但它及 `tqdm`、`tensorboardX`、`h5py` 尚未全部纳入依赖锁文件。
- **WSL 路径干扰**：如果从新终端运行，建议检查 `PATH` 中是否有 Windows Anaconda 路径干扰；避免无必要地修改全局 `PATH`。

## 复现进度

- [x] 环境搭建（venv + PyTorch + CUDA）
- [x] DIV2K 训练集/验证集下载与解压
- [x] 从 HR 生成 x2 LR 图像（`generate_lr.py`）
- [x] 修改 `src/meta_learning.sh` 适配本地路径与 8GB 显存
- [x] 跑通 smoke test（`--epochs 2`，PSNR 22.877）
- [x] 完整元学习训练（50 epochs，最佳 PSNR 32.252 @epoch 46）
- [x] VSD4K 数据集下载与解压（`lol_15s_1`，495 帧 HR + X2 LR）
- [ ] 元调优阶段（`meta_tuning`）
- [ ] 梯度掩码分析与结果评估

## 参考

- 论文：[ECCV 2022] Efficient Meta-Tuning for Content-Aware Neural Video Delivery
- 官方代码：https://github.com/Neural-video-delivery/EMT-Pytorch-ECCV2022
- DIV2K 数据集：https://data.vision.ee.ethz.ch/cvl/DIV2K/
- VSD4K 数据集（用于元调优）：可从 CaFM-Pytorch-ICCV2021 仓库获取

## 许可

本仓库仅用于学术复现与学习，代码版权归原作者所有。
