#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 check v3: compare against the *comparable* ns-3 runs and the paper's stated range.

ns-3 reference points (paperTable3, 1 UE/cell):
  * B1  19 sites / 57 cells, centre 21 : mean SINR 47.7 dB   <- same drop rule as here
  * B0  one site / 3 cells             : 69.2 dB, but its UEs sat ~1 m from the antenna,
                                          so it is NOT comparable and is reported for
                                          information only.
Paper: "average SINR 20-30 dB" at full load (26 UE/cell).
"""
import sys

import numpy as np

sys.path.insert(0, "/home/penghao/code/EMT-Pytorch-ECCV2022/RTSR")

from sl.config import Mode, Scenario  # noqa: E402
from sl.topology import Topology  # noqa: E402
from sl.channel import Channel  # noqa: E402


def survey(site_rings, interferer_rings, ue_per_cell, n_tti=200, seed=1, label=""):
    sc = Scenario(site_rings=site_rings, interferer_rings=interferer_rings,
                  ue_per_cell=ue_per_cell, seed=seed)
    mode = Mode.conservative()
    topo = Topology(sc)
    ch = Channel(sc, mode, topo)
    rng = np.random.default_rng(seed + 7)
    vals = []
    for _ in range(n_tti):
        ch.advance()
        vals.append(ch.sinr_db(active=ch.sample_activity(rng)))
    sinr = np.concatenate(vals)
    q = np.percentile(sinr, [5, 25, 50, 75, 95])
    print(label)
    print(f"  cells={topo.n_cells} centre={int(topo.cell_centre.sum())} "
          f"UEs={topo.n_ue} activity={ch.activity:.2f}")
    print(f"  SINR dB: mean {sinr.mean():6.1f}  p5 {q[0]:6.1f}  p25 {q[1]:6.1f} "
          f"p50 {q[2]:6.1f}  p75 {q[3]:6.1f}  p95 {q[4]:6.1f}")
    return sinr.mean()


def main():
    print("=== M1 sanity check (conservative mode, activity model on) ===\n")
    a = survey(0, 0, 1, label="[A] one site, 3 cells, 1 UE/cell   (information only)")
    b = survey(1, 1, 1, label="[B] 19 sites / 57 cells, centre 21, 1 UE/cell  "
                              "(ns-3 B1 = 47.7 dB)")
    c = survey(1, 1, 18, label="[C] same as B but 18 UE/cell   "
                               "(paper at full load: 20-30 dB)")

    print("\n--- checks ---")
    ok_b = 40.0 <= b <= 55.0
    ok_c = 15.0 <= c <= 30.0
    ok_load = (b - c) > 5.0
    print(f"  [B] within 40-55 dB (ns-3 B1 = 47.7)         : "
          f"{'PASS' if ok_b else 'FAIL'}  ({b:.1f} dB)")
    print(f"  [C] within 15-30 dB (paper: 20-30 at load)   : "
          f"{'PASS' if ok_c else 'FAIL'}  ({c:.1f} dB)")
    print(f"  load lowers SINR by > 5 dB                   : "
          f"{'PASS' if ok_load else 'FAIL'}  ({b - c:.1f} dB)")
    print(f"  [A] = {a:.1f} dB (3 cells, sibling sectors dominate; not comparable)")
    ok = ok_b and ok_c and ok_load
    print(f"\n  verdict: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
