#!/usr/bin/env bash
# 元学习（MAML 预训练）的启动脚本：在 DIV2K 上训练一个通用初始化。

set -euo pipefail

cd "$(dirname "$0")"

CUDA_VISIBLE_DEVICES=0 python main.py \
    --model espcn \
    --scale 2 \
    --patch_size 144 \
    --batch_size 8 \
    --n_threads 4 \
    --use_maml \
    --maml \
    --save local_maml_espcn_x2_p144_b8_smoke_e2 \
    --epochs 2 \
    --decay 400-650 \
    --reset \
    --data_train DIV2K \
    --data_test DIV2K \
    --data_range 1-750/751-800 \
    --istype4few50 \
    --inner_lr 5e-06 \
    --inner_lr_decay 2.5e-6 \
    --dir_data /home/penghao/code/EMT-Pytorch-ECCV2022/data/DIV2K \
    --save_every \
    --lr 1e-3 \
    --test_every 100
