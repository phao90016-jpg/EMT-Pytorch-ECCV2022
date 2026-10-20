#!/usr/bin/env bash
# Paper-aligned Table II: 1080p LD encoded at 3-5 Mbps -> 2160p HD.
set -euo pipefail
cd "$(dirname "$0")"

bash tools/encode_ld_4k.sh
bash tools/prepare_4k_bins.sh

cd src
PY="${PY:-/home/penghao/code/EMT-Pytorch-ECCV2022/emt-env/bin/python}"
EPOCHS="${EPOCHS:-30}"
RATES="3000 3500 4000 4500 5000"

for R in $RATES; do
  echo "=== M2 @ ${R} kbps (1080p -> 2160p) ==="
  "$PY" main.py --template RTSR_M2 --model EDSR --scale 2 --patch_size 96 --batch_size 16 \
    --epochs "$EPOCHS" --lr 1e-4 --data_train DIV2K --data_test DIV2K \
    --data_range 1-400/401-495 --dir_data "../dataset/4k_b${R}" \
    --print_every 100 --n_threads 4 --save "../experiment_t2_4k_b${R}"
done

"$PY" ../tools/collect_table2.py --pattern 'experiment_t2_4k_b*' \
  --data-dir 'dataset/4k_b{}' --out TABLE2_4K.md \
  --desc '1080p LD encoded at 3-5 Mbps -> 2160p HD (paper Table II setting)'