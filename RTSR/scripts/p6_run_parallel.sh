#!/usr/bin/env bash
# P6 parallel sweep runner.
#
# Same contract as p6_run.sh (idempotent: a run with a DONE marker is skipped), but runs
# up to JOBS simulations concurrently.  Each job gets its own work directory, its own
# watchdog, its own run.log and its own summary line collected at the end (never
# concurrently appended by several jobs).
#
# Usage:  bash RTSR/scripts/p6_run_parallel.sh <manifest> [jobs]
set -uo pipefail
BIN=/home/penghao/code/ns-allinone-3.39/ns-3.39/build/src/nr/examples/ns3.39-cttc-nr-traffic-3gpp-xr-optimized
REPO=/home/penghao/code/EMT-Pytorch-ECCV2022
MANIFEST=${1:-$REPO/RTSR/scripts/p6_manifest.txt}
JOBS=${2:-3}
ROOT=$REPO/RTSR/results/p6
WORK=/tmp/p6work
SUMMARY=$ROOT/summary2.csv
HEADER="run,ues,frames,satisfied,satisfied_pct,mean_fsr_paper,mean_fsr_e2e,dropped_frames"

COMMON="--trafficModel=paper --preset=paperTable3 --sectorized=1 --numSectors=3 \
--siteRings=1 --statsRings=1 --indoorRatio=0.8 --ueSpeedKmh=3 --tddPattern=DDDSU \
--checkpointEveryMs=5000 --warmupMs=1000 --progressEveryMs=250 \
--enablePing=0 --flowmonProbes=0 --rngRun=1"

mkdir -p "$ROOT" "$WORK"
[ -f "$SUMMARY" ] || echo "$HEADER" > "$SUMMARY"

run_one()
{
  local id=$1 args=$2 dst="$ROOT/$1" wd="$WORK/$1"
  if [ -f "$dst/DONE" ]; then
    echo "[skip] $id (already done)"
    return 0
  fi
  mkdir -p "$dst"
  rm -rf "$wd"; mkdir -p "$wd"
  cd "$wd" || return 1
  echo "[run ] $id  $args"
  local start
  start=$(date +%s)
  # shellcheck disable=SC2086
  "$BIN" $COMMON $args > "$dst/run.log" 2>&1 &
  local simpid=$!
  # watchdog: wall clock + simulated time + the *pids* cpu/elapsed, every 5 min
  (
    while sleep 300; do
      simms=$(sed -n 's/^simulated_ms,//p' progress.txt 2>/dev/null)
      cpu=$(ps -o etime=,time= -p "$simpid" --no-headers 2>/dev/null | tr -s ' ')
      echo "$(date '+%F %T') pid=$simpid sim_ms=${simms:-?} proc=${cpu:-gone}" \
        >> "$dst/watchdog.log"
    done
  ) &
  local wpid=$!
  wait "$simpid"
  local rc=$?
  kill "$wpid" 2>/dev/null
  local wall=$(( $(date +%s) - start ))
  echo "[exit] $id rc=$rc wall=${wall}s"
  cp -f ./*.csv ./*.xml ./checkpoint.txt "$dst"/ 2>/dev/null
  if [ "$rc" -eq 0 ] && grep -q '^complete,1' "$dst/checkpoint.txt" 2>/dev/null; then
    touch "$dst/DONE"
    ( cd "$REPO" && python3 RTSR/layer_stats.py --dir "$dst" --out "$dst/layer_report.md" \
        > /dev/null 2>&1 )
    # one job writes its own line; the parent merges them at the end
    python3 "$REPO/RTSR/scripts/p6_stats.py" "$dst" > "$dst/summary_line.txt" 2>/dev/null
    echo "[ok  ] $id archived"
  else
    echo "[WARN] $id did not finish (rc=$rc); partial data kept, no DONE marker"
  fi
}

# ---- launch with a simple concurrency limit ----
n=0
while IFS='|' read -r id args; do
  [[ -z "${id:-}" ]] && continue
  [[ "$id" == \#* ]] && continue
  mkdir -p "$ROOT/$id"          # the redirect below needs the directory to exist
  ( run_one "$id" "$args" ) > "$ROOT/$id/runner.log" 2>&1 &
  n=$((n + 1))
  while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 15; done
done < "$MANIFEST"
wait

# ---- merge the per-run summary lines (order: as produced) ----
for f in "$ROOT"/*/summary_line.txt; do
  [ -f "$f" ] || continue
  run=$(basename "$(dirname "$f")")
  grep -q "^$run," "$SUMMARY" || cat "$f" >> "$SUMMARY"
done
echo "--- cumulative summary:"
cat "$SUMMARY"
