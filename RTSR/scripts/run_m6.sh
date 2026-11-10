#!/usr/bin/env bash
# M6: 36 runs (6 UE/cell points x 2 schemes x 3 seeds), 1000 s each, 5 in parallel.
set -uo pipefail
cd /home/penghao/code/EMT-Pytorch-ECCV2022 || exit 1

OUT=sl/results/m6
LOG=sl/results/m6/logs
mkdir -p "$OUT" "$LOG"
MAXJOBS=5

echo "=== M6 start $(date '+%F %T') ===" | tee -a "$LOG/runner.log"

run_one() {
    ue=$1; scheme=$2; seed=$3
    tag="${ue}-${scheme}-s${seed}"
    echo "[start] $tag $(date '+%T')" >> "$LOG/runner.log"
    emt-env/bin/python RTSR/sl/run_point.py --ue "$ue" --scheme "$scheme" \
        --seed "$seed" --duration 1000 --out "$OUT" > "$LOG/$tag.log" 2>&1
    rc=$?
    echo "[done]  $tag rc=$rc $(date '+%T')" >> "$LOG/runner.log"
}

n=0
for ue in 6 9 12 15 18 23; do
    for scheme in conv rtsr; do
        for seed in 1 2 3; do
            run_one "$ue" "$scheme" "$seed" &
            n=$((n + 1))
            while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do sleep 20; done
        done
    done
done
wait
echo "=== M6 all done $(date '+%F %T') ===" | tee -a "$LOG/runner.log"

python3 - "$OUT" <<'PY'
import csv, glob, os, sys
rows = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.csv"))):
    with open(f) as fh:
        rows += [r for r in csv.DictReader(fh)]
if rows:
    rows.sort(key=lambda r: (int(r["ue"]), r["scheme"], int(r["seed"])))
    print(f"{'ue':>3} {'scheme':<5} {'sat%':>7} {'fsr%':>7} {'Mbps':>7}")
    for r in rows:
        print(f"{r['ue']:>3} {r['scheme']:<5} {r['satisfied_pct']:>7} "
              f"{r['mean_fsr_pct']:>7} {r['carried_mbps']:>7}")
    print(f"\n{len(rows)} runs")
PY
