#!/usr/bin/env bash
# RTSR Table II: LD bitrate -> quality, specialised model vs a general one.
#
#   bash run_table2.sh
#   EPOCHS=4 bash run_table2.sh      # smoke
set -euo pipefail

cd "$(dirname "$0")/src"
PY="${PY:-/home/penghao/code/EMT-Pytorch-ECCV2022/emt-env/bin/python}"
EPOCHS="${EPOCHS:-30}"
RATES="750 875 1000 1125 1250 2500"

common=(
  --template RTSR_M2 --model EDSR --scale 2 --patch_size 96 --batch_size 16
  --epochs "$EPOCHS" --lr 1e-4 --data_train DIV2K --data_test DIV2K
  --data_range 1-400/401-495 --print_every 100 --n_threads 4
)

for R in $RATES; do
  echo "=== specialised M2 @ ${R} kbps ==="
  "$PY" main.py "${common[@]}" --dir_data "../dataset/ld_b${R}" --save "../experiment_t2_b${R}"
done

echo "=== general baseline (DIV2K images, no target video) ==="
"$PY" main.py --template RTSR_M2 --model EDSR --scale 2 --patch_size 96 --batch_size 16 \
  --epochs "$EPOCHS" --lr 1e-4 --data_train DIV2K --data_test DIV2K \
  --data_range 1-800/801-900 --dir_data ../../EMT-Pytorch-ECCV2022/data \
  --print_every 100 --n_threads 4 --save ../experiment_t2_general

echo "=== general model applied to every LD variant ==="
for R in $RATES; do
  echo "--- general on b${R} ---"
  "$PY" main.py --template RTSR_M2 --model EDSR --scale 2 --data_test DIV2K \
    --data_range 401-495 --dir_data "../dataset/ld_b${R}" --test_only \
    --pre_train ../experiment_t2_general/model/model_best.pt \
    --save "../experiment_t2_gen_on_b${R}"
done

"$PY" ../tools/collect_table2.py