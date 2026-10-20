#!/usr/bin/env bash
# RTSR Table I at the paper's resolution: 1080p LD -> 2160p HD.
#
#   bash run_table1_4k.sh            # M1, M2, M3 (29 epochs each)
#   bash run_table1_4k.sh m1 m2      # subset
#   EPOCHS=2 bash run_table1_4k.sh m1   # smoke
#
# Source: Big Buck Bunny 3840x2160p30 (CG animation), frames 120-136 s,
# LR = 1920x1080 bicubic downscale. Built by tools/make_4k_dataset.sh.
set -euo pipefail

cd "$(dirname "$0")/src"
PY="${PY:-/home/penghao/code/EMT-Pytorch-ECCV2022/emt-env/bin/python}"
EPOCHS="${EPOCHS:-30}"

common=(
  --model EDSR --scale 2 --patch_size 96 --batch_size 16
  --epochs "$EPOCHS" --lr 1e-4
  --data_train DIV2K --data_test DIV2K --data_range 1-400/401-495
  --dir_data ../dataset/4k_bbb --print_every 100 --n_threads 4
)

run_one() {
  echo "=== 4K ${1} (${2}) ==="
  "$PY" main.py "${common[@]}" --template "$2" --save "../experiment_4k_${1}"
}

variants=("$@")
if [ "${#variants[@]}" -eq 0 ]; then
  variants=(m1 m2 m3)
fi

for v in "${variants[@]}"; do
  case "$v" in
    m1) run_one m1_9feats  RTSR_M1 ;;
    m2) run_one m2_26feats RTSR_M2 ;;
    m3) run_one m3_64feats RTSR_M3 ;;
    *) echo "unknown variant: $v (use m1 / m2 / m3)" >&2; exit 2 ;;
  esac
done

"$PY" ../tools/collect_table1.py --pattern 'experiment_4k_*' --out TABLE1_4K.md \
--desc '1080p -> 2160p, Big Buck Bunny 4K (CG); LD is a clean bicubic downscale with NO compression, train 1-400, eval 401-495'
