#!/usr/bin/env bash
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
