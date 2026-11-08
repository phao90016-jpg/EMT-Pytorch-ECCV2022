#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M5: run the ideal mode (OFDMA + ideal beam + 3GPP curves + O2I) and see where the knee lands.

Paper targets: both schemes >90% below 17 UE/cell, conventional collapses after 18,
RTSR holds to ~23.
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


def run(scheme, ue_per_cell, duration_s=6.0, seed=1, warmup_s=1.0):
    mode = Mode.ideal()
    sc = Scenario(ue_per_cell=ue_per_cell, duration_s=duration_s, seed=seed)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=ue_per_cell * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    tr = Traffic(sc, mode, topo, seed=seed, capacity_mbps_per_cell=350.0)
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
        grants = sch.schedule(sinr, link, tr.backlog_bytes)
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
    print("=== M5: ideal mode (OFDMA + ideal beam + 3GPP curves + O2I) ===\n")
    print(f"{'UE/cell':>7} {'scheme':<13} {'satisfied':>10} {'FSR':>7} {'Mbps':>7}")
    for ue in (12, 18, 23):
        for scheme in ("conventional", "rtsr"):
            r = run(scheme, ue)
            print(f"{ue:>7} {scheme:<13} {r['satisfied_pct']:>9.1f}% "
                  f"{r['mean_fsr_pct']:>6.1f}% {r['carried_mbps']:>6.0f}")
    print("\npaper targets: both >90% below 17; conventional collapses after 18; RTSR holds to ~23")


if __name__ == "__main__":
    sys.exit(main())
