#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run one M6 point: 1000 s, ideal mode, one scheme, one seed -> one CSV line.

Usage:
    python run_point.py --ue 18 --scheme rtsr --seed 1 --duration 1000 --out sl/results/m6
"""
import argparse
import io
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sl.config import Mode, Scenario  # noqa: E402
from sl.topology import Topology  # noqa: E402
from sl.channel import Channel  # noqa: E402
from sl.link import Link  # noqa: E402
from sl.scheduler import Scheduler  # noqa: E402
from sl.traffic import Traffic  # noqa: E402
from sl.metrics import summary  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ue", type=int, required=True)
    ap.add_argument("--scheme", choices=("conv", "rtsr"), required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--duration", type=float, default=1000.0)
    ap.add_argument("--warmup", type=float, default=60.0)
    ap.add_argument("--out", default="sl/results/m6")
    args = ap.parse_args()

    mode = Mode.ideal()
    sc = Scenario(ue_per_cell=args.ue, duration_s=args.duration, seed=args.seed)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=args.ue * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    tr = Traffic(sc, mode, topo, seed=args.seed, capacity_mbps_per_cell=380.0)
    if args.scheme == "rtsr":
        tr.bitrate_mbps = 10.0
        tr.model_bytes_per_s = 530.0 * 1024.0 / 6.0
        tr.model_bytes_per_tti = tr.model_bytes_per_s * sc.tti_s

    active = np.array([len(topo.cell_ues[ci]) > 0 for ci in range(topo.n_cells)])
    warm = int(round(args.warmup / sc.tti_s))
    bits = 0.0
    t0 = time.time()
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
        if t % 200000 == 0 and t:
            el = time.time() - t0
            print(f"  [{args.ue}{args.scheme}s{args.seed}] {t}/{sc.n_tti} "
                  f"({el:.0f}s, {t/el:.0f} TTI/s)", flush=True)

    mbps = bits / ((sc.n_tti - warm) * sc.tti_s) / int(topo.cell_centre.sum()) / 1e6
    r = summary(tr, topo, args.ue)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{args.ue}-{args.scheme}-s{args.seed}.csv")
    new = not os.path.exists(path)
    with io.open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("ue,scheme,seed,ues,frames,satisfied_pct,mean_fsr_pct,carried_mbps,"
                    "wall_s\n")
        f.write(f"{args.ue},{args.scheme},{args.seed},{r['ues']},{r['frames']},"
                f"{r['satisfied_pct']:.2f},{r['mean_fsr_pct']:.2f},{mbps:.1f},"
                f"{time.time()-t0:.0f}\n")
    print(f"done {args.ue}/{args.scheme}/s{args.seed}: satisfied {r['satisfied_pct']:.1f}% "
          f"FSR {r['mean_fsr_pct']:.1f}% {mbps:.0f} Mbps "
          f"({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
