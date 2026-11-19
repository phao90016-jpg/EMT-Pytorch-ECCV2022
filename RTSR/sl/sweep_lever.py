#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""杠杆扫描：在系统级仿真器里改一个假设，看满意率曲线怎么动。

用途：阶段三要找"把拐点从 14.8 推到 17.5"的杠杆。这个脚本让我们快速试不同假设，
不用每次改代码。

当前支持的杠杆：
  --tdd N       TDD 下行占比（**注意：主仿真循环未使用该参数，改它无效**，见 docs/stage3/03 第 12 节）
  --pf-decay N  比例公平的指数遗忘因子（默认 0.98 = 记忆 25 ms）
                PDB 只有 10 ms，记忆窗口比截止时间还长 2.5 倍，可能导致调度器反应不过来。
                0.90 = 记忆 5 ms，0.80 = 记忆 2.5 ms
  --pdb-ms N    帧的截止时间（毫秒，默认 10，论文值）
                用来做敏感性：若论文的"成功"判据比我们松，拐点会右移多少

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


def run_one(ue_per_cell, tdd, duration, warmup, seed, pf_decay=None, pdb_ms=None,
            interferer_rings=1):
    mode = Mode.ideal()
    sc = Scenario(ue_per_cell=ue_per_cell, duration_s=duration, seed=seed,
                  tdd_dl_fraction=tdd, interferer_rings=interferer_rings)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=ue_per_cell * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    if pf_decay is not None:
        sch.decay = pf_decay
    tr = Traffic(sc, mode, topo, seed=seed, capacity_mbps_per_cell=380.0)
    if pdb_ms is not None:
        tr.pdb_tti = max(1, int(round((pdb_ms * 1e-3) / sc.tti_s)))

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
    # 把"队列溢出"与"真实超时"分开统计（只算中心 UE）
    m = topo.ue_is_centre
    sent = float(tr.frames_sent[m].sum())
    ok = float(tr.frames_ok[m].sum())
    noslot = float(tr.frames_noslot[m].sum())
    r["noslot_pct"] = 100.0 * noslot / sent if sent else 0.0
    r["fail_pct"] = 100.0 * (sent - ok) / sent if sent else 0.0
    r["noslot_share_of_fail"] = (
        100.0 * noslot / (sent - ok) if (sent - ok) > 0 else 0.0)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tdd", type=float, default=0.70, help="TDD 下行占比（主循环未使用）")
    ap.add_argument("--pf-decay", type=float, default=None,
                    help="比例公平的遗忘因子；0.98 = 25 ms 记忆，0.90 = 5 ms")
    ap.add_argument("--pdb-ms", type=float, default=None,
                    help="帧截止时间（毫秒），默认 10；用于敏感性分析")
    ap.add_argument("--interferer-rings", type=int, default=1,
                    help="外圈干扰站圈数；0 = 21 小区（快 2.7 倍，用于杠杆筛选），1 = 57 小区")
    ap.add_argument("--ues", type=int, nargs="+", default=[12, 15, 18])
    ap.add_argument("--duration", type=float, default=200.0)
    ap.add_argument("--warmup", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    print("pf_decay = %s  pdb = %s  rings = %d  (duration %.0f s, seed %d)"
          % ("default" if args.pf_decay is None else "%.2f" % args.pf_decay,
             "default" if args.pdb_ms is None else "%.0f ms" % args.pdb_ms,
             args.interferer_rings, args.duration, args.seed))
    print("%8s %12s %12s %10s %10s %14s"
          % ("UE/cell", "satisfied%", "meanFSR%", "fail%", "noslot%", "noslot/fail%"))
    print("-" * 74)
    for ue in args.ues:
        r = run_one(ue, args.tdd, args.duration, args.warmup, args.seed,
                    args.pf_decay, args.pdb_ms, args.interferer_rings)
        print("%8d %12.2f %12.2f %10.2f %10.2f %14.1f"
              % (ue, r["satisfied_pct"], r["mean_fsr_pct"],
                 r["fail_pct"], r["noslot_pct"], r["noslot_share_of_fail"]),
              flush=True)


if __name__ == "__main__":
    main()