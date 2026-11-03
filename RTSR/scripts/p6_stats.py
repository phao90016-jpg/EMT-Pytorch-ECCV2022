#!/usr/bin/env python3
"""Fig.5 metric for one run directory (paper definition).

A UE is satisfied when its frame success rate is above 99.5%, where a frame succeeds if
it was fully delivered and not dropped at the BS buffer (PDB 10 ms = QCI 68).

Inputs (all written by the simulation):
  frame_per_ue.csv   ue,port,sent,seen,complete,in_pdb_e2e
  rlc_drops.csv      frame_id,dropped_sdus   (frame_id = ue<<20 | counter)

Prints one CSV line:
  run,ues,frames,satisfied,satisfied_pct,mean_fsr_paper,mean_fsr_e2e,dropped_frames
"""
import csv
import glob
import os
import sys


def read_per_ue(run_dir):
    path = os.path.join(run_dir, "frame_per_ue.csv")
    if not os.path.isfile(path):
        return None
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append({k: int(float(v)) for k, v in r.items()})
            except (KeyError, ValueError):
                continue
    return rows or None


def read_drops_by_ue(run_dir):
    """frame_id = ue<<20 | counter, so the UE is recoverable from the id."""
    path = os.path.join(run_dir, "rlc_drops.csv")
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                fid = int(float(r["frame_id"]))
                n = int(float(r["dropped_sdus"]))
            except (KeyError, ValueError):
                continue
            ue = fid >> 20
            rec = out.setdefault(ue, {"frames": set(), "sdus": 0})
            rec["frames"].add(fid)
            rec["sdus"] += n
    return out


def legacy_per_ue(run_dir):
    """Fallback for runs made before frame_per_ue.csv existed."""
    rows = []
    for path in sorted(glob.glob(os.path.join(run_dir, "frame_stats_port*_ue*.csv"))):
        ue = int(os.path.basename(path).split("_ue")[-1].split(".")[0])
        seen = comp = pdb = 0
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                seen += 1
                comp += 1 if r.get("complete") == "1" else 0
                pdb += 1 if r.get("within_pdb") == "1" else 0
        rows.append({"ue": ue, "sent": seen, "seen": seen, "complete": comp, "in_pdb_e2e": pdb})
    return rows or None


def main(run_dir):
    name = os.path.basename(run_dir.rstrip("/"))
    per_ue = read_per_ue(run_dir)
    if per_ue is None:
        per_ue = legacy_per_ue(run_dir)
        if per_ue is None:
            print(f"{name},0,0,0,0.00,0.000,0.000,0")
            return
        sys.stderr.write("warning: frame_per_ue.csv missing, fell back to frame_stats\n")

    drops = read_drops_by_ue(run_dir)
    n = len(per_ue)
    total_frames = sum(r.get("sent", 0) for r in per_ue)
    satisfied = 0
    sum_paper = 0.0
    sum_e2e = 0.0
    dropped_frames = 0
    for r in per_ue:
        sent = r.get("sent", 0)
        ue = r.get("ue", -1)
        dropped_frames += len(drops.get(ue, {}).get("frames", ()))
        if sent <= 0:
            continue
        # A frame dropped at the BS can never be "complete", so complete/sent already
        # matches the paper's definition (we do not subtract drops again).
        fsr_paper = 100.0 * r.get("complete", 0) / sent
        fsr_e2e = 100.0 * r.get("in_pdb_e2e", 0) / sent
        sum_paper += fsr_paper
        sum_e2e += fsr_e2e
        if fsr_paper >= 99.5:
            satisfied += 1
    print(
        f"{name},{n},{total_frames},{satisfied},{100.0 * satisfied / n:.2f},"
        f"{sum_paper / n:.3f},{sum_e2e / n:.3f},{dropped_frames}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: p6_stats.py <run dir>")
    main(sys.argv[1])
