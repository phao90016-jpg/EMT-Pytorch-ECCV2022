#!/usr/bin/env bash
# Reproduce RTSR (WCNC 2023) Table I: EDSR M1 / M2 / M3, x2, 540p -> 1080p.
#
#   bash run_table1.sh              # all three variants
#   bash run_table1.sh m1 m2        # selected variants
#   EPOCHS=2 bash run_table1.sh m1  # quick smoke run
#
# Note: --epochs N actually trains N-1 epochs (terminate() uses
# last_epoch + 1 >= epochs), so EPOCHS=30 gives 29 epochs, the same budget as
# experiment_rtsr_m2_32feats.
set -euo pipefail

cd "$(dirname "$0")/src"

PY="${PY:-/home/penghao/code/EMT-Pytorch-ECCV2022/emt-env/bin/python}"
EPOCHS="${EPOCHS:-30}"

common=(
  --model EDSR
  --scale 2
  --patch_size 96
  --batch_size 16
  --epochs "$EPOCHS"
  --lr 1e-4
  --data_train DIV2K
  --data_test DIV2K
  --data_range 1-400/401-495
  --dir_data ../dataset
  --print_every 100
  --n_threads 4
)

run_one() {
  local tag="$1"
  local tmpl="$2"
  echo "=== ${tag}: --template ${tmpl}, epochs=${EPOCHS} ==="
  "$PY" main.py "${common[@]}" --template "$tmpl" --save "../experiment_${tag}"
}

variants=("$@")
if [ "${#variants[@]}" -eq 0 ]; then
  variants=(m1 m2 m3)
fi

for v in "${variants[@]}"; do
  case "$v" in
    m1) run_one rtsr_m1_9feats  RTSR_M1 ;;
    m2) run_one rtsr_m2_26feats RTSR_M2 ;;
    m3) run_one rtsr_m3_64feats RTSR_M3 ;;
    *) echo "unknown variant: $v (use m1 / m2 / m3)" >&2; exit 2 ;;
  esac
done

"$PY" ../tools/collect_table1.py