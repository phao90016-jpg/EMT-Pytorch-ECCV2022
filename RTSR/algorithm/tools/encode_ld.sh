#!/usr/bin/env bash
# Encode the LD stream at the bitrates used by RTSR Table II (rescaled by pixel count).
#
#   bash tools/encode_ld.sh            # all five bitrates
#   RATES="750 1250" bash tools/encode_ld.sh
#
# 1080p source frames -> 960x540 -> x264 2-pass at R kbps -> decoded PNG frames,
# laid out so that src/data/div2k.py can read them unchanged:
#   dataset/ld_b<R>/DIV2K/DIV2K_train_HR            (symlink to the 1080p frames)
#   dataset/ld_b<R>/DIV2K/DIV2K_train_LR_bicubic/X2 (compressed 540p, %05dx2.png)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DATASET="$ROOT/dataset"
HR_DIR="$SRC_DATASET/DIV2K/DIV2K_train_HR"
RATES="${RATES:-750 875 1000 1125 1250}"
FPS=30

test -d "$HR_DIR" || { echo "HR dir missing: $HR_DIR" >&2; exit 1; }

for R in $RATES; do
  TAG="ld_b${R}"
  WORK="$SRC_DATASET/$TAG"
  X2="$WORK/DIV2K/DIV2K_train_LR_bicubic/X2"
  rm -rf "$WORK"
  mkdir -p "$X2"

  echo "=== ${R} kbps ==="
  ffmpeg -hide_banner -loglevel error -y -framerate $FPS -i "$HR_DIR/%05d.png" \
    -vf "scale=960:540:flags=bicubic" -c:v libx264 -preset medium -pix_fmt yuv420p \
    -b:v "${R}k" -maxrate "${R}k" -bufsize "$((R*2))k" -pass 1 -passlogfile "/tmp/x264_$TAG" \
    -an -f mp4 /dev/null

  ffmpeg -hide_banner -loglevel error -y -framerate $FPS -i "$HR_DIR/%05d.png" \
    -vf "scale=960:540:flags=bicubic" -c:v libx264 -preset medium -pix_fmt yuv420p \
    -b:v "${R}k" -maxrate "${R}k" -bufsize "$((R*2))k" -pass 2 -passlogfile "/tmp/x264_$TAG" \
    -an "$WORK/${TAG}.mp4"

  ffmpeg -hide_banner -loglevel error -y -i "$WORK/${TAG}.mp4" -vsync 0 -start_number 1 \
    "$X2/%05dx2.png"

  ln -sfn "$HR_DIR" "$WORK/DIV2K/DIV2K_train_HR"

  SIZE=$(stat -c %s "$WORK/${TAG}.mp4")
  N=$(ls "$X2" | wc -l)
  BITRATE_KBPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=bit_rate -of default=nw=1:nk=1 "$WORK/${TAG}.mp4")
  echo "  frames=${N}  file=$((SIZE/1024)) KiB  measured=$((BITRATE_KBPS/1000)) kbps"
done
echo "done"