#!/usr/bin/env python3
"""M3 check: reproduce the ns-3 satisfied ratios at 6 and 12 UE/cell.

ns-3 reference (6 s, TDMA, B1-fixed):
    6 UE/cell : conventional 96.83%, RTSR 99.21%
   12 UE/cell : conventional  2.78%, RTSR 88.10%
   18 UE/cell : conventional  0.00%

Tolerance +/- 12 pp: the link abstraction and the scheduler fairness are approximations.
What must come out right is the shape - conventional collapses between 6 and 12 while
RTSR stays high - and the satisfied ratio is computed exactly like the paper (per-UE
FSR > 99.5%).
"""
import sys

import numpy as np

sys.path.insert(0, "/home/penghao/code/EMT-Pytorch-ECCV2022/RTSR")

from sl.config import Mode, Scenario  # noqa: E402
from sl.topology import Topology  # noqa: E402
from sl.channel import Channel  # noqa: E402
from sl.link import Link  # noqa: E402
from sl.scheduler import Scheduler  # noqa: E402
from sl.traffic import Traffic  # noqa: E402
from sl.metrics import summary  # noqa: E402


def run(scheme, ue_per_cell, duration_s=6.0, seed=1, warmup_s=1.0, rb_util=None):
    mode = Mode.conservative()
    sc = Scenario(ue_per_cell=ue_per_cell, duration_s=duration_s, seed=seed)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=ue_per_cell * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    if rb_util is not None:
        sch.rb_utilization = rb_util
    # capacity per cell from the ns-3 stage: 125 / 191 / 145 Mbps at 6 / 12 / 18 UE/cell
    cap = {6: 125.0, 12: 191.0, 18: 145.0}.get(ue_per_cell, 190.0)
    tr = Traffic(sc, mode, topo, seed=seed, capacity_mbps_per_cell=cap)
    if scheme == "rtsr":
        tr.bitrate_mbps = 10.0
        tr.model_bytes_per_s = 530.0 * 1024.0 / 6.0
        tr.model_bytes_per_tti = tr.model_bytes_per_s * sc.tti_s

    active = np.array([len(topo.cell_ues[ci]) > 0 for ci in range(topo.n_cells)])
    warm = int(round(warmup_s / sc.tti_s))
    bits = 0.0
    for t in range(sc.n_tti):
        ch.advance()
        tr.step(t)
        if t == warm:
            tr.reset_counters()
            bits = 0.0
        sinr = ch.sinr_db(active=active)
        grants = sch.schedule(sinr, link, tr.backlog_bytes, tr.frame_backlog_bytes)
        served = np.zeros(topo.n_ue)
        sizes = []
        for (ci, ues, n_rb) in grants:
            b = np.minimum(link.tb_bytes(n_rb, sinr[ues]), tr.backlog_bytes[ues])
            served[ues] += b
            sizes.append((ues, b))
            if topo.cell_centre[ci]:
                bits += float(b.sum()) * 8.0
        tr.serve(served)
        sch.update_rates(grants, sizes)

    mbps = bits / ((sc.n_tti - warm) * sc.tti_s) / int(topo.cell_centre.sum()) / 1e6
    r = summary(tr, topo, ue_per_cell)
    r["carried_mbps"] = mbps
    return r


def main():
    ref = {(6, "conventional"): 96.83, (6, "rtsr"): 99.21,
           (12, "conventional"): 2.78, (12, "rtsr"): 88.10,
           (18, "conventional"): 0.00}
    print("=== M3 check: satisfied UE ratio vs the ns-3 stage ===\n")
    print(f"{'UE/cell':>7} {'scheme':<13} {'sim':>8} {'ns-3':>8} {'diff':>8} "
          f"{'FSR':>7} {'Mbps':>7}")
    ok_all = True
    for ue in (6, 12, 18):
        for scheme in ("conventional", "rtsr"):
            if (ue, scheme) not in ref:
                continue
            r = run(scheme, ue)
            sim, ref_v = r["satisfied_pct"], ref[(ue, scheme)]
            diff = sim - ref_v
            ok = abs(diff) <= 12.0
            ok_all &= ok
            print(f"{ue:>7} {scheme:<13} {sim:>7.1f}% {ref_v:>7.1f}% {diff:>+7.1f}  "
                  f"{r['mean_fsr_pct']:6.1f}% {r['carried_mbps']:6.0f}  "
                  f"{'PASS' if ok else 'FAIL'}")
    print(f"\n  verdict: {'PASS' if ok_all else 'FAIL'} (tolerance +/-12 pp)")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
