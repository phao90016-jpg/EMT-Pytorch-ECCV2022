#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-UE FSR + SE diagnostic for the system-level simulator (stage 3, P1).

Answers "who loses frames": dumps every UE's FSR, refusal count and mean SE, so the
low-SE tail can be separated from a uniform loss.

    emt-env/bin/python RTSR/sl/diag_fsr_tail.py --ue 6 --duration 100 --scheme conv

Finding (2026-11-15, 6 UE/cell, 100 s): mean FSR 97.96%, 78.07% satisfied; the 75 UEs
with refusals have mean SE 1.75 b/RE vs 6.64 for the rest -> the FSR ceiling is set by
the SINR low tail, not by the HOL rule itself.
"""
import argparse
import sys
import time

import numpy as np

sys.path.insert(0, "/home/penghao/code/EMT-Pytorch-ECCV2022/RTSR")

from sl.config import Mode, Scenario          # noqa: E402
from sl.topology import Topology              # noqa: E402
from sl.channel import Channel                # noqa: E402
from sl.link import Link                      # noqa: E402
from sl.scheduler import Scheduler            # noqa: E402
from sl.traffic import Traffic                # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ue", type=int, default=6)
    ap.add_argument("--duration", type=float, default=100.0)
    ap.add_argument("--warmup", type=float, default=10.0)
    ap.add_argument("--scheme", choices=("conv", "rtsr"), default="conv")
    ap.add_argument("--scheduler", choices=("tdma", "ofdma_pf"), default=None,
                    help="override the scheduler only (channel stays ideal)")
    ap.add_argument("--icic-db", type=float, default=None,
                    help="override Mode.icic_atten_db (inter-cell interference suppression)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--site-rings", type=int, default=1,
                    help="0 = single site; 1 = 7 sites (21 cells)")
    ap.add_argument("--interferer-rings", type=int, default=2,
                    help="outer rings used as interference sources (0 = none, like ns-3 P6)")
    ap.add_argument("--top", type=int, default=8, help="print the N worst/best UEs")
    args = ap.parse_args()

    mode = Mode.ideal()
    if args.scheduler:
        mode.scheduler = args.scheduler
    if args.icic_db is not None:
        mode.icic_atten_db = args.icic_db
    sc = Scenario(ue_per_cell=args.ue, duration_s=args.duration, seed=args.seed,
                  site_rings=args.site_rings, interferer_rings=args.interferer_rings)
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
    se_acc = np.zeros(topo.n_ue)
    se_n = np.zeros(topo.n_ue)
    sinr_acc = np.zeros(topo.n_ue)
    t0 = time.time()

    for t in range(sc.n_tti):
        ch.advance()
        tr.step(t)
        if t == warm:
            tr.reset_counters()
            se_acc[:] = 0.0
            se_n[:] = 0
            sinr_acc[:] = 0.0
        sinr = ch.sinr_db(active=active)
        grants = sch.schedule(sinr, link, tr.backlog_bytes, tr.frame_backlog_bytes)
        served = np.zeros(topo.n_ue)
        sizes = []
        for (ci, ues, n_rb) in grants:
            b = np.minimum(link.tb_bytes(n_rb, sinr[ues]), tr.backlog_bytes[ues])
            served[ues] += b
            sizes.append((ues, b))
            se_acc[ues] += link.se(sinr[ues])
            sinr_acc[ues] += sinr[ues]
            se_n[ues] += 1
        tr.serve(served)
        sch.update_rates(grants, sizes)

    sent = tr.frames_sent.astype(float)
    ok = tr.frames_ok.astype(float)
    fsr = np.where(sent > 0, 100.0 * ok / np.maximum(sent, 1), 0.0)
    mean_se = np.where(se_n > 0, se_acc / np.maximum(se_n, 1), 0.0)
    mean_sinr = np.where(se_n > 0, sinr_acc / np.maximum(se_n, 1), -99.0)

    print("cells=%d (centre %d)  site_rings=%d  interferer_rings=%d  scheduler=%s  icic=%.1f dB"
          % (topo.n_cells, int(topo.cell_centre.sum()), args.site_rings,
             args.interferer_rings, mode.scheduler, mode.icic_atten_db))
    print("wall %.0fs  UE=%d  mean FSR=%.2f%%  satisfied=%d (%.2f%%)"
          % (time.time() - t0, topo.n_ue, fsr.mean(), int((fsr >= 99.5).sum()),
             100.0 * (fsr >= 99.5).mean()))

    order = np.argsort(fsr)
    print("\nue   sent   ok   failed   FSR%   meanSE  meanSINR  backlog_B")
    for label, idx in (("worst", order[:args.top]), ("best", order[-min(4, len(order)):])):
        print("-- %s --" % label)
        for i in idx:
            print("  %4d %5d %4d %6d %7.2f %8.2f %9.2f %9.0f"
                  % (i, sent[i], ok[i], sent[i] - ok[i], fsr[i],
                     mean_se[i], mean_sinr[i], tr.frame_backlog_bytes[i]))

    bad = fsr < 99.5
    print("\nfailing UEs=%d (%.1f%%)  their mean SE=%.2f / SINR=%.1f dB"
          % (int(bad.sum()), 100.0 * bad.mean(),
             mean_se[bad].mean() if bad.any() else 0.0,
             mean_sinr[bad].mean() if bad.any() else 0.0))
    print("clean   UEs=%d (%.1f%%)  their mean SE=%.2f / SINR=%.1f dB"
          % (int((~bad).sum()), 100.0 * (~bad).mean(),
             mean_se[~bad].mean() if (~bad).any() else 0.0,
             mean_sinr[~bad].mean() if (~bad).any() else 0.0))
    print("frame failure rate = %.2f%% of frames" % (100.0 * (sent - ok).sum() / max(sent.sum(), 1)))
    print("SINR percentiles: p5=%.1f p10=%.1f p50=%.1f dB"
          % tuple(np.percentile(mean_sinr[se_n > 0], [5, 10, 50])))
    return 0


if __name__ == "__main__":
    sys.exit(main())