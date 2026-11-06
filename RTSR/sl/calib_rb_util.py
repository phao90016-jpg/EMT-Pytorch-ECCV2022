#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibrate the conservative mode's RB utilisation.

The conservative mode has to reproduce the ns-3 stage's *saturation point*: at 12 UE/cell
the cell delivers ~191 of the 240 Mbps demanded, and that mere 20% deficit makes almost
every frame miss the 10 ms PDB.  Sweep rb_utilization and report the satisfied ratios.
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


def one(ue_per_cell, rb_util, scheme, duration_s=6.0, seed=1, warmup_s=1.0):
    mode = Mode.conservative()
    sc = Scenario(ue_per_cell=ue_per_cell, duration_s=duration_s, seed=seed)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=ue_per_cell * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    sch.rb_utilization = rb_util
    tr = Traffic(sc, mode, topo, seed=seed)
    if scheme == "rtsr":
        tr.bitrate_mbps = 10.0
        tr.model_bytes_per_s = 530.0 * 1024.0 / 6.0
        tr.model_bytes_per_tti = tr.model_bytes_per_s * sc.tti_s

    active = np.array([len(topo.cell_ues[ci]) > 0 for ci in range(topo.n_cells)])
    warm = int(round(warmup_s / sc.tti_s))
    bits = 0.0
    for t in range(sc.n_tti):
        ch.advance()
        tr.now_tti = t
        tr.step(t)
        tr.drop_expired()
        if t == warm:
            tr.reset_counters()
            bits = 0.0
        sinr = ch.sinr_db(active=active)
        grants = sch.schedule(sinr, link, tr.backlog_bytes)
        served = np.zeros(topo.n_ue)
        sizes = []
        for (ci, ues, n_rb) in grants:
            b = link.tb_bytes(n_rb, sinr[ues])
            b = np.minimum(b, tr.rem[ues].sum(axis=1))
            served[ues] += b
            sizes.append((ues, b))
            if topo.cell_centre[ci]:
                bits += float(b.sum()) * 8.0
        tr.serve(served)
        sch.update_rates(grants, sizes)

    mbps = bits / ((sc.n_tti - warm) * sc.tti_s) / int(topo.cell_centre.sum()) / 1e6
    r = summary(tr, topo, ue_per_cell)
    return r["satisfied_pct"], mbps


def main():
    print("rb_util | 6-conv | 12-conv | 12-rtsr | carried@12conv")
    print("--------|--------|---------|---------|----------------")
    for rb in (0.40, 0.50, 0.60, 0.70):
        s6c, _ = one(6, rb, "conventional")
        s12c, m12c = one(12, rb, "conventional")
        s12r, _ = one(12, rb, "rtsr")
        print(f"  {rb:.2f}  | {s6c:5.1f}% | {s12c:6.1f}% | {s12r:6.1f}% | {m12c:6.1f} Mbps")
    print("\n(targets: 6-conv ~96.8, 12-conv ~2.8, 12-rtsr ~88.1, carried@12conv ~191)")


if __name__ == "__main__":
    main()
