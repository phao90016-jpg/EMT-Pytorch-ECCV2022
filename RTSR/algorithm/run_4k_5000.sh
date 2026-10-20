#!/usr/bin/env bash
# Complete the 5 Mbps point at 2160p: M1 and M3 on top of the existing M2,
# then compute VMAF for all five bitrates and summarise.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-/home/penghao/code/EMT-Pytorch-ECCV2022/emt-env/bin/python}"
EPOCHS="${EPOCHS:-30}"
DATA=../dataset/4k_b5000

cd src
for V in m1:9feats:RTSR_M1 m3:64feats:RTSR_M3; do
  NAME=${V%%:*}
  REST=${V#*:}
  TAG=${REST%%:*}
  TMPL=${REST#*:}
  echo "=== 5000 kbps ${NAME} (${TMPL}) ==="
  "$PY" main.py --template "$TMPL" --model EDSR --scale 2 --patch_size 96 --batch_size 16 \
    --epochs "$EPOCHS" --lr 1e-4 --data_train DIV2K --data_test DIV2K \
    --data_range 1-400/401-495 --dir_data "$DATA" \
    --print_every 100 --n_threads 4 --save "../experiment_4k_${TAG}_b5000"
done
cd ..

echo "=== VMAF for the five 4K bitrates ==="
"$PY" tools/make_vmaf.py --pattern 'experiment_t2_4k_b{}' --data-dir 'dataset/4k_b{}' \
  --rates 3000 3500 4000 4500 5000 --out vmaf_results_4k.json

"$PY" tools/collect_table2.py --pattern 'experiment_t2_4k_b*' \
  --data-dir 'dataset/4k_b{}' --out TABLE2_4K.md \
  --desc '1080p LD encoded at 3-5 Mbps -> 2160p HD (paper Table II setting); Big Buck Bunny 4K (CG)'