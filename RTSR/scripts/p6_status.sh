#!/usr/bin/env bash
# P6 status overview - one command to see everything that is running or finished.
#
#   bash RTSR/scripts/p6_status.sh
#
# Reading it: "进度" is the simulated time out of the planned duration; "剩余" extrapolates
# from the last heartbeat's average rate.  In the watchdog column the two time fields must
# BOTH grow: if elapsed grows while cpu does not, the host was suspended or throttled.
set -uo pipefail
REPO=/home/penghao/code/EMT-Pytorch-ECCV2022
ROOT=$REPO/RTSR/results/p6
WORK=/tmp/p6work

echo "==================== $(date '+%F %T') ===================="
echo "== simulations running =="
n=0
while read -r pid etime ctime rest; do
  [ -z "${pid:-}" ] && continue
  n=$((n + 1))
  printf "  pid=%-7s elapsed=%-10s cpu=%-10s %s\n" "$pid" "$etime" "$ctime" "$rest"
done < <(ps -eo pid=,etime=,time=,args= | grep 'xr-optimized --' | grep -v grep)
[ "$n" -eq 0 ] && echo "  (none)"
echo "  memory: $(free -g | awk 'NR==2{print "used "$3" GB / total "$2" GB, available "$7" GB"}')"

echo
echo "== runs =="
printf "%-14s %-18s %-12s %-10s %s\n" RUN PROGRESS RATE REMAINING WATCHDOG
for wd in "$WORK"/p6-*; do
  [ -d "$wd" ] || continue
  id=$(basename "$wd")
  pf=$wd/progress.txt
  if [ -f "$ROOT/$id/DONE" ]; then
    printf "%-14s %-18s %-12s %-10s %s\n" "$id" "DONE" "-" "-" "finished"
    continue
  fi
  # hide leftovers from earlier experiments: no DONE, no heartbeat, or a stale heartbeat
  if [ ! -f "$pf" ]; then
    [ -n "$(find "$wd" -maxdepth 1 -newermt '-30 minutes' -name '*.log' 2>/dev/null)" ] \
      && printf "%-14s %-18s %-12s %-10s %s\n" "$id" "(starting)" "-" "-" "-"
    continue
  fi
  if [ -z "$(find "$pf" -newermt '-3 hours' 2>/dev/null)" ]; then
    continue   # heartbeat older than an hour and not finished: an abandoned leftover
  fi
  sim=$(sed -n 's/^simulated_ms,//p' "$pf")
  plan=$(sed -n 's/^planned_ms,//p' "$pf")
  wall=$(sed -n 's/^wall_s,//p' "$pf")
  rate=$(awk -v w="$wall" -v s="$sim" 'BEGIN{ if (s>0) printf "%.0f", w*1000/s; else printf "-" }')
  remain=$(awk -v w="$wall" -v s="$sim" -v p="$plan" 'BEGIN{
      if (s>0) { sec = w*(p-s)/s; if (sec>3600) printf "%.1f h", sec/3600; else printf "%.0f min", sec/60 }
      else printf "-" }')
  wl=$(tail -1 "$ROOT/$id/watchdog.log" 2>/dev/null | cut -c12-23,25-)
  printf "%-14s %-18s %-12s %-10s %s\n" "$id" "${sim}/${plan} ms" "${rate} s/s" "$remain" "${wl:--}"
done

echo
echo "== summary2.csv (paper definition) =="
column -s, -t < "$ROOT/summary2.csv" 2>/dev/null || cat "$ROOT/summary2.csv"
