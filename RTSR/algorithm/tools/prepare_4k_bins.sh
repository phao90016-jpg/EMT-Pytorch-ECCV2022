#!/usr/bin/env bash
# Reuse the 4K HR pickle cache (built by the first 4K run) in every bitrate variant.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/dataset/4k_bbb/DIV2K/bin/DIV2K_train_HR"
test -d "$SRC" || { echo "4K cache missing, run the 4K training once first" >&2; exit 1; }
for D in "$ROOT"/dataset/4k_b*; do
  test -d "$D" || continue
  TGT="$D/DIV2K/bin/DIV2K_train_HR"
  if [ -d "$TGT" ] && [ "$(ls "$TGT" | wc -l)" -ge 495 ]; then
    echo "skip $D"
    continue
  fi
  mkdir -p "$TGT"
  cp -al "$SRC"/. "$TGT"/
  echo "seeded $D"
done