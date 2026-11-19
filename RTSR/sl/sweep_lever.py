#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""杠杆扫描：在系统级仿真器里改一个假设，看满意率曲线怎么动。

用途：阶段三要找"把拐点从 14.8 推到 17.5"的杠杆。这个脚本让我们快速试不同假设，
不用每次改代码。

当前支持的杠杆：
  --tdd N       TDD 下行占比（默认 0.70 = DDDSU 把 S 时隙算半个下行）
                0.80 = 把 S 时隙整个算作下行（系统级论文常见做法）

用法：
  python3 RTSR/sl/sweep_lever.py --tdd 0.7 --ues 12 15 18 --duration 200
  python3 RTSR/sl/sweep_lever.py --tdd 0.8 --ues 12 15 18 --duration 200
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sl.config import Mode, Scenario          # noqa: E402
from sl.topology import Topology              # noqa: E402
from sl.channel import Channel                # noqa: E402
from sl.link import Link                      # noqa: E402
from sl.scheduler import Scheduler            # noqa: E402
from sl.traffic import Traffic                # noqa: E402
from sl.metrics import summary                # noqa: E402


def run_one(ue_per_cell, tdd, duration, warmup, seed):
    mode = Mode.ideal()
    sc = Scenario(ue_per_cell=ue_per_cell, duration_s=duration, seed=seed,
                  tdd_dl_fraction=tdd)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=ue_per_cell * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    tr = Traffic(sc, mode, topo, seed=seed, capacity_mbps_per_cell=380.0)

    active = np.array([len(topo.cell_ues[ci]) > 0 for ci in range(topo.n_cells)])
    warm = int(round(warmup / sc.tti_s))

    for t in range(sc.n_tti):
        ch.advance()
        tr.step(t)
        if t == warm:
            tr.reset_counters()
        sinr = ch.sinr_db(active=active)
        grants = sch.schedule(sinr, link, tr.backlog_bytes, tr.frame_backlog_bytes)
        served = np.zeros(topo.n_ue)
        sizes = []
        for (ci, ues, n_rb) in grants:
            b = np.minimum(link.tb_bytes(n_rb, sinr[ues]), tr.backlog_bytes[ues])
            served[ues] += b
            sizes.append((ues, b))
        tr.serve(served)
        sch.update_rates(grants, sizes)

    r = summary(tr, topo, ue_per_cell)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tdd", type=float, default=0.70, help="TDD 下行占比")
    ap.add_argument("--ues", type=int, nargs="+", default=[12, 15, 18])
    ap.add_argument("--duration", type=float, default=200.0)
    ap.add_argument("--warmup", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    print("TDD DL fraction = %.2f  (duration %.0f s, seed %d)"
          % (args.tdd, args.duration, args.seed))
    print("%8s %12s %12s" % ("UE/cell", "satisfied%", "meanFSR%"))
    print("-" * 36)
    for ue in args.ues:
        r = run_one(ue, args.tdd, args.duration, args.warmup, args.seed)
        print("%8d %12.2f %12.2f"
              % (ue, r["satisfied_pct"], r["mean_fsr_pct"]), flush=True)


if __name__ == "__main__":
    main()