#!/usr/bin/env bash
# P6 / T4 sweep runner.
#
# Idempotent: a run whose result directory contains a DONE marker is skipped, so the
# sweep can be stopped at any time and restarted with the same command.  ns-3 cannot
# resume a *single* run (no checkpoint/restore) - the checkpointing inside the
# simulator only keeps the data of an interrupted run up to its last flush.
#
# Usage:  bash RTSR/scripts/p6_run.sh [manifest]
set -uo pipefail
BIN=/home/penghao/code/ns-allinone-3.39/ns-3.39/build/src/nr/examples/ns3.39-cttc-nr-traffic-3gpp-xr-optimized
REPO=/home/penghao/code/EMT-Pytorch-ECCV2022
MANIFEST=${1:-$REPO/RTSR/scripts/p6_manifest.txt}
ROOT=$REPO/RTSR/results/p6
WORK=/tmp/p6work

# T4 common configuration: 7 sites = 21 cells (no outer ring, see the deviation note),
# 100 MHz/Table III preset, 80% indoor, 3 km/h, DDDSU, checkpoint every 5 s, RngRun 1.
COMMON="--trafficModel=paper --preset=paperTable3 --sectorized=1 --numSectors=3 \
--siteRings=1 --statsRings=1 --indoorRatio=0.8 --ueSpeedKmh=3 --tddPattern=DDDSU \
--checkpointEveryMs=5000 --warmupMs=1000 --progressEveryMs=250 \
--enablePing=0 --flowmonProbes=0 --rngRun=1"

mkdir -p "$ROOT" "$WORK"
[ -f "$ROOT/summary2.csv" ] || echo "run,ues,frames,satisfied,satisfied_pct,mean_fsr_paper,mean_fsr_e2e,dropped_frames" > "$ROOT/summary2.csv"

while IFS='|' read -r id args; do
  [[ -z "${id:-}" ]] && continue
  [[ "$id" == \#* ]] && continue
  dst="$ROOT/$id"
  if [ -f "$dst/DONE" ]; then
    echo "[skip] $id (already done)"
    continue
  fi
  mkdir -p "$dst"
  wd="$WORK/$id"
  rm -rf "$wd"; mkdir -p "$wd"
  cd "$wd" || exit 1
  echo "[run ] $id  $COMMON $args"
  start=$(date +%s)
  # shellcheck disable=SC2086
  "$BIN" $COMMON $args > "$dst/run.log" 2>&1
  rc=$?
  wall=$(( $(date +%s) - start ))
  echo "[exit] $id rc=$rc wall=${wall}s"
  cp -f ./*.csv ./*.xml ./checkpoint.txt "$dst"/ 2>/dev/null
  if [ "$rc" -eq 0 ] && grep -q '^complete,1' "$dst/checkpoint.txt" 2>/dev/null; then
    touch "$dst/DONE"
    ( cd "$REPO" && python3 RTSR/layer_stats.py --dir "$dst" --out "$dst/layer_report.md" \
        > /dev/null 2>&1 )
    python3 "$REPO/RTSR/scripts/p6_stats.py" "$dst" >> "$ROOT/summary2.csv" 2>/dev/null
    echo "[ok  ] $id archived + summarised"
  else
    echo "[WARN] $id did not finish; partial data kept (see checkpoint.txt), no DONE marker"
  fi
done < "$MANIFEST"
