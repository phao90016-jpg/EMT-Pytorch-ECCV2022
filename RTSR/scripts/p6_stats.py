#!/usr/bin/env python3
"""Fig.5 metric for one run directory.

Paper definition: a UE is satisfied when its frame success rate is above 99.5%.
Frame success is the sink's own accounting: a frame counts as successful when every
packet arrived and its end-to-end delay stayed within the frame PDB.

Prints one CSV line:  run,ues,frames,satisfied,satisfied_pct,mean_fsr
"""
import csv
import glob
import os
import sys


def main(run_dir):
    rows = []
    for path in sorted(glob.glob(os.path.join(run_dir, "frame_stats_port*_ue*.csv"))):
        seen = complete = in_pdb = 0
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                seen += 1
                complete += 1 if r.get("complete") == "1" else 0
                in_pdb += 1 if r.get("within_pdb") == "1" else 0
        if seen:
            rows.append((seen, complete, in_pdb, 100.0 * in_pdb / seen))
    total_frames = sum(r[0] for r in rows)
    if not rows:
        print(f"{os.path.basename(run_dir.rstrip('/'))},0,0,0,0.00,0.000")
        return
    satisfied = sum(1 for r in rows if r[3] >= 99.5)
    mean_fsr = sum(r[3] for r in rows) / len(rows)
    print(
        f"{os.path.basename(run_dir.rstrip('/'))},{len(rows)},{total_frames},"
        f"{satisfied},{100.0 * satisfied / len(rows):.2f},{mean_fsr:.3f}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: p6_stats.py <run dir>")
    main(sys.argv[1])
