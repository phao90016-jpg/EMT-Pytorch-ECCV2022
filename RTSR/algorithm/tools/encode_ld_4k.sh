#!/usr/bin/env bash
# Encode the paper's actual setting: 1080p LD at 3-5 Mbps -> 2160p HD.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/dataset/4k_bbb/DIV2K/DIV2K_train_LR_bicubic/X2"
HR="$ROOT/dataset/4k_bbb/DIV2K/DIV2K_train_HR"
RATES="${RATES:-3000 3500 4000 4500 5000}"
FPS=30

test -d "$SRC" || { echo "missing 1080p source: $SRC" >&2; exit 1; }

for R in $RATES; do
  TAG="4k_b${R}"
  WORK="$ROOT/dataset/$TAG"
  LR="$WORK/DIV2K/DIV2K_train_LR_bicubic/X2"
  rm -rf "$WORK"
  mkdir -p "$LR"

  echo "=== ${R} kbps ==="
  ffmpeg -hide_banner -loglevel error -y -framerate $FPS -i "$SRC/%05dx2.png" \
    -c:v libx264 -preset medium -pix_fmt yuv420p \
    -b:v "${R}k" -maxrate "${R}k" -bufsize "$((R*2))k" -pass 1 -passlogfile "/tmp/x264_$TAG" \
    -an -f mp4 /dev/null
  ffmpeg -hide_banner -loglevel error -y -framerate $FPS -i "$SRC/%05dx2.png" \
    -c:v libx264 -preset medium -pix_fmt yuv420p \
    -b:v "${R}k" -maxrate "${R}k" -bufsize "$((R*2))k" -pass 2 -passlogfile "/tmp/x264_$TAG" \
    -an "$WORK/$TAG.mp4"

  ffmpeg -hide_banner -loglevel error -y -i "$WORK/$TAG.mp4" -vsync 0 -start_number 1 \
    "$LR/%05dx2.png"
  ln -sfn "$HR" "$WORK/DIV2K/DIV2K_train_HR"

  SIZE=$(stat -c %s "$WORK/$TAG.mp4")
  KBPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=bit_rate -of default=nw=1:nk=1 "$WORK/$TAG.mp4")
  echo "  frames=$(ls "$LR" | wc -l)  file=$((SIZE/1024)) KiB  measured=$((KBPS/1000)) kbps"
done
echo done