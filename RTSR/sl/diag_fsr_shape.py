#!/usr/bin/env python3
"""Step 2: per-UE FSR distribution from the ns-3 frame_stats files (one row per frame)."""
import glob
import io
import os

BASE = "/home/penghao/code/EMT-Pytorch-ECCV2022/RTSR/results/p6"


def load_run(run):
    fsr = []
    for f in sorted(glob.glob(os.path.join(BASE, run, "frame_stats_port*_ue*.csv"))):
        rows = io.open(f, encoding="utf-8").read().strip().split("\n")
        if len(rows) < 2:
            continue
        hdr = [h.strip() for h in rows[0].split(",")]
        if "complete" not in hdr:
            continue
        ci = hdr.index("complete")
        vals = []
        for line in rows[1:]:
            p = line.split(",")
            if len(p) > ci:
                try:
                    vals.append(float(p[ci]))
                except ValueError:
                    pass
        if vals:
            fsr.append(sum(vals) / len(vals))
    return fsr


for run in ("p6-6-conv", "p6-6-rtsr"):
    fsr = load_run(run)
    n = len(fsr)
    if n == 0:
        print(run, "no data")
        continue
    zero = sum(1 for x in fsr if x < 0.005)
    good = sum(1 for x in fsr if x > 0.995)
    mid = n - zero - good
    print(f"{run}: UEs={n}  mean FSR={100*sum(fsr)/n:.2f}%  "
          f"FSR<0.5%: {zero} ({100*zero/n:.0f}%)  "
          f"0.5-99.5%: {mid} ({100*mid/n:.0f}%)  "
          f"FSR>99.5%: {good} ({100*good/n:.0f}%)")
