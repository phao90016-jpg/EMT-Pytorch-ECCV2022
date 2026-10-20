#!/usr/bin/env bash
# Hard-link the shared 1080p HR pickle cache into every LD variant, so that
# training only has to build the (small) 540p LR cache.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/dataset/DIV2K/bin/DIV2K_train_HR"

for D in "$ROOT"/dataset/ld_b*; do
  test -d "$D" || continue
  TGT="$D/DIV2K/bin/DIV2K_train_HR"
  if [ -d "$TGT" ] && [ "$(ls "$TGT" | wc -l)" -ge 495 ]; then
    echo "skip $D (cache present)"
    continue
  fi
  mkdir -p "$TGT"
  cp -al "$SRC"/. "$TGT"/
  echo "seeded $D ($(ls "$TGT" | wc -l) HR caches)"
done