#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统级仿真器的每 UE FSR + 频谱效率诊断工具（阶段三 P1）。

回答的问题是「**到底是谁在丢帧**」：把每个 UE 的 FSR、失败帧数、平均 SE 全打出来，
这样就能区分"低 SE 尾部在丢帧"和"所有 UE 均匀地丢一点"。

    emt-env/bin/python RTSR/sl/diag_fsr_tail.py --ue 6 --duration 100 --scheme conv

历史发现（2026-11-15，6 UE/cell，100 s）：平均 FSR 97.96%、满意率 78.07%；
有失败帧的 75 个 UE 平均 SE 只有 1.75 b/RE，其余 UE 是 6.64 —— **FSR 天花板是 SINR
低尾造成的，不是 HOL 规则本身**。这条结论直接引出了后来的 ICIC 16 dB 标定。

常用开关：
    --icic-db N        覆盖 Mode.icic_atten_db（做敏感性扫描用）
    --scheduler X      只换调度器，信道仍是理想档
    --interferer-rings 0  不要外圈干扰源（对齐 ns-3 P6 的拓扑）
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
    ap.add_argument("--ue", type=int, default=6, help="每小区终端数")
    ap.add_argument("--duration", type=float, default=100.0, help="仿真时长（秒）")
    ap.add_argument("--warmup", type=float, default=10.0, help="预热时长（秒）")
    ap.add_argument("--scheme", choices=("conv", "rtsr"), default="conv")
    ap.add_argument("--scheduler", choices=("tdma", "ofdma_pf"), default=None,
                    help="只换调度器（信道仍是理想档）")
    ap.add_argument("--icic-db", type=float, default=None,
                    help="覆盖 Mode.icic_atten_db（邻区干扰抑制量）")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--site-rings", type=int, default=1,
                    help="0 = 单站；1 = 7 站（21 小区）")
    ap.add_argument("--interferer-rings", type=int, default=2,
                    help="外圈干扰源的圈数（0 = 不要，和 ns-3 P6 的拓扑一致）")
    ap.add_argument("--top", type=int, default=8, help="打印最差/最好的 N 个 UE")
    args = ap.parse_args()

    mode = Mode.ideal()
    if args.scheduler:
        mode.scheduler = args.scheduler        # 命令行覆盖调度器
    if args.icic_db is not None:
        mode.icic_atten_db = args.icic_db      # 命令行覆盖 ICIC 抑制量
    sc = Scenario(ue_per_cell=args.ue, duration_s=args.duration, seed=args.seed,
                  site_rings=args.site_rings, interferer_rings=args.interferer_rings)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=args.ue * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    tr = Traffic(sc, mode, topo, seed=args.seed, capacity_mbps_per_cell=380.0)
    if args.scheme == "rtsr":
        # RTSR：视频码率减半 + 模型流
        tr.bitrate_mbps = 10.0
        tr.model_bytes_per_s = 530.0 * 1024.0 / 6.0
        tr.model_bytes_per_tti = tr.model_bytes_per_s * sc.tti_s

    active = np.array([len(topo.cell_ues[ci]) > 0 for ci in range(topo.n_cells)])
    warm = int(round(args.warmup / sc.tti_s))

    # 每 UE 的累加器：SE、SINR、被调度次数
    se_acc = np.zeros(topo.n_ue)
    se_n = np.zeros(topo.n_ue)
    sinr_acc = np.zeros(topo.n_ue)
    t0 = time.time()

    for t in range(sc.n_tti):
        ch.advance()
        tr.step(t)
        if t == warm:
            # 预热结束：计数器与累加器一起清零
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
            # 只统计"真正被调度到"的 UE 的 SE 与 SINR（没被调度的没有样本）
            se_acc[ues] += link.se(sinr[ues])
            sinr_acc[ues] += sinr[ues]
            se_n[ues] += 1
        tr.serve(served)
        sch.update_rates(grants, sizes)

    # ---- 汇总 ----
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

    # 按 FSR 排序，打出最差和最好的几个 UE
    order = np.argsort(fsr)
    print("\nue   sent   ok   failed   FSR%   meanSE  meanSINR  backlog_B")
    for label, idx in (("worst", order[:args.top]), ("best", order[-min(4, len(order)):])):
        print("-- %s --" % label)
        for i in idx:
            print("  %4d %5d %4d %6d %7.2f %8.2f %9.2f %9.0f"
                  % (i, sent[i], ok[i], sent[i] - ok[i], fsr[i],
                     mean_se[i], mean_sinr[i], tr.frame_backlog_bytes[i]))

    # 关键对比：失败 UE 与正常 UE 的 SE / SINR 差多少
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