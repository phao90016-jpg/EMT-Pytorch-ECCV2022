#!/usr/bin/env bash
# P6 容量重算（去重键修复后）。
#
# 背景：旧的 results/p6 是用带 bug 的二进制跑的，MAC 字节计数器会把
# "同槽位不同大小"的真 TB 当成重复 trace 丢掉，导致容量少算 20-35%。
# 本脚本用修复后的二进制重跑同样的配置，输出到 results/p6_recalc/，
# 保留旧结果用于对照。
#
# 与 p6_run.sh 的区别：
#   1) 输出目录不同（不覆盖旧结果）
#   2) 4 路并行（16 核，单条 ns-3 是单线程）
#   3) 不做 layer_report 汇总（由后续脚本统一处理）
#
# 用法： bash RTSR/scripts/p6_recalc.sh [manifest] [并发数]
set -uo pipefail
BIN=/home/penghao/code/ns-allinone-3.39/ns-3.39/build/src/nr/examples/ns3.39-cttc-nr-traffic-3gpp-xr-optimized
REPO=/home/penghao/code/EMT-Pytorch-ECCV2022
MANIFEST=${1:-$REPO/RTSR/scripts/p6_manifest_recalc.txt}
JOBS=${2:-4}
ROOT=$REPO/RTSR/results/p6_recalc
WORK=/tmp/p6recalc

COMMON="--trafficModel=paper --preset=paperTable3 --sectorized=1 --numSectors=3 \
--siteRings=1 --statsRings=1 --indoorRatio=0.8 --ueSpeedKmh=3 --tddPattern=DDDSU \
--checkpointEveryMs=5000 --warmupMs=1000 --progressEveryMs=250 \
--enablePing=0 --flowmonProbes=0 --rngRun=1"

mkdir -p "$ROOT" "$WORK"

run_one() {
  local id="$1" args="$2"
  local dst="$ROOT/$id" wd="$WORK/$id"
  if [ -f "$dst/DONE" ]; then echo "[skip] $id"; return 0; fi
  mkdir -p "$dst"; rm -rf "$wd"; mkdir -p "$wd"
  echo "[run ] $id"
  local start; start=$(date +%s)
  ( cd "$wd" && "$BIN" $COMMON $args > "$dst/run.log" 2>&1 )
  local rc=$?
  local wall=$(( $(date +%s) - start ))
  cp -f "$wd"/*.csv "$wd"/*.xml "$wd"/checkpoint.txt "$dst"/ 2>/dev/null
  if [ "$rc" -eq 0 ] && grep -q '^complete,1' "$dst/checkpoint.txt" 2>/dev/null; then
    touch "$dst/DONE"
    echo "[ok  ] $id wall=${wall}s"
  else
    echo "[WARN] $id rc=$rc wall=${wall}s (partial kept)"
  fi
}

# 简单并发控制：每 JOBS 条等一次
n=0
while IFS='|' read -r id args; do
  [ -z "${id:-}" ] && continue
  [ "${id:0:1}" = "#" ] && continue
  run_one "$id" "$args" &
  n=$((n+1))
  if [ $((n % JOBS)) -eq 0 ]; then wait; fi
done < "$MANIFEST"
wait
echo "[all ] done"