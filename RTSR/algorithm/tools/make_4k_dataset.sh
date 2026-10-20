#!/usr/bin/env bash
# Build the 1080p -> 2160p dataset (paper setting) from the 4K source.
set -euo pipefail
SRC=/home/penghao/code/dataset_4k/bbb_sunflower_2160p_30fps_normal.mp4
OUT=/home/penghao/code/EDSR-PyTorch/dataset/4k_bbb/DIV2K
HR="$OUT/DIV2K_train_HR"
LR="$OUT/DIV2K_train_LR_bicubic/X2"
START=${START:-120}
N=495

mkdir -p "$HR" "$LR"

echo "== extracting $N frames at 3840x2160 from ${START}s =="
ffmpeg -hide_banner -loglevel error -y -ss "$START" -i "$SRC" -frames:v "$N" -vsync 0 \
  "$HR/%05d.png"

echo "== extracting $N frames at 1920x1080 (LD) =="
ffmpeg -hide_banner -loglevel error -y -ss "$START" -i "$SRC" -frames:v "$N" -vsync 0 \
  -vf "scale=1920:1080:flags=bicubic" "$LR/%05dx2.png"

echo "HR: $(ls "$HR" | wc -l) files, $(du -sh "$HR" | cut -f1)"
echo "LR: $(ls "$LR" | wc -l) files, $(du -sh "$LR" | cut -f1)"