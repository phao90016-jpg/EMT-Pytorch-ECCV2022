#!/usr/bin/env bash
# Online-training window sweep (paper Q2: update period vs freshness/quality).
#
#   bash run_dt_sweep.sh                 # windows 60 / 180 / 400 frames
#   EPOCHS=4 bash run_dt_sweep.sh        # quick smoke
#
# At 30 fps the windows correspond to ~2 s / 6 s / 13 s. The clip is only 15 s
# long, so the paper's 30-60 s update periods cannot be measured here; they are
# covered analytically by the model-overhead table in TABLE1.md.
set -euo pipefail

cd "$(dirname "$0")/src"

PY="${PY:-/home/penghao/code/EMT-Pytorch-ECCV2022/emt-env/bin/python}"
EPOCHS="${EPOCHS:-30}"

for frames in 60 180 400; do
  echo "=== window ${frames} frames ==="
  "$PY" main.py \
    --template RTSR_M2 \
    --model EDSR --scale 2 --patch_size 96 --batch_size 16 \
    --epochs "$EPOCHS" --lr 1e-4 \
    --data_train DIV2K --data_test DIV2K \
    --data_range "1-${frames}/401-495" \
    --dir_data ../dataset --print_every 100 --n_threads 4 \
    --save "../experiment_dt_${frames}f"
done

"$PY" ../tools/collect_dt.py