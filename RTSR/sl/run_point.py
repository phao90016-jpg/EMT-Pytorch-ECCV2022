#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑 M6 的一个点：1000 s、理想档、一个方案、一个种子 -> 输出一行 CSV。

这是整个系统级仿真的**主循环入口**。一次调用只跑一个 (UE数, 方案, 种子) 组合，
M6 全量是 6 点 x 2 方案 x 3 种子 = 36 次调用。

用法：
    python run_point.py --ue 18 --scheme rtsr --seed 1 --duration 1000 --out RTSR/sl/results/m6

每 TTI 的处理顺序（顺序本身有意义，不要随意调换）：
    1. channel.advance()      刷新快衰落（到相干时间才真正重抽）
    2. traffic.step(t)        先让过期帧作废，再处理新到达的帧
    3. （warm-up 边界）       清零计数器
    4. channel.sinr_db()      算本 TTI 的 SINR
    5. scheduler.schedule()   分配 RB
    6. link.tb_bytes()        把 RB 数换算成能装的字节
    7. traffic.serve()        把字节喂给帧队列（整帧发完才计成功）
    8. scheduler.update_rates() 更新比例公平的历史速率
"""
import argparse
import io
import os
import sys
import time

import numpy as np

# 把 RTSR/ 加进搜索路径，这样才能 `from sl.xxx import ...`
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
    ap.add_argument("--ue", type=int, required=True, help="每小区终端数")
    ap.add_argument("--scheme", choices=("conv", "rtsr"), required=True,
                    help="conv = 传统纯视频 20 Mbps；rtsr = 视频 10 Mbps + 模型流")
    ap.add_argument("--seed", type=int, default=1, help="随机种子（撒点/衰落/抖动都用它派生）")
    ap.add_argument("--duration", type=float, default=1000.0, help="仿真时长（秒）")
    ap.add_argument("--warmup", type=float, default=60.0,
                    help="预热时长（秒），这段的统计会被丢弃")
    ap.add_argument("--out", default="sl/results/m6", help="结果目录")
    args = ap.parse_args()

    # 一律用理想档：OFDMA + 理想波束 + 3GPP 曲线 + 帧级 PDB
    mode = Mode.ideal()
    sc = Scenario(ue_per_cell=args.ue, duration_s=args.duration, seed=args.seed)
    topo = Topology(sc)
    # 小区活跃度按提供负载估：每 UE 20 Mbps（两种方案都一样，因为模型流很小）
    ch = Channel(sc, mode, topo, load_per_cell_mbps=args.ue * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)
    tr = Traffic(sc, mode, topo, seed=args.seed, capacity_mbps_per_cell=380.0)

    if args.scheme == "rtsr":
        # RTSR 方案：视频码率减半，另加一条模型更新流
        # 模型流 = 530 KB / 6 s（论文的数字），按 TTI 摊平后不会瞬时冲垮 RLC 缓冲
        tr.bitrate_mbps = 10.0
        tr.model_bytes_per_s = 530.0 * 1024.0 / 6.0
        tr.model_bytes_per_tti = tr.model_bytes_per_s * sc.tti_s

    # 理想档下所有小区全程发射（不做随机活跃度），干扰是最坏情况
    active = np.array([len(topo.cell_ues[ci]) > 0 for ci in range(topo.n_cells)])
    warm = int(round(args.warmup / sc.tti_s))
    bits = 0.0                      # 只累计中心小区的承载比特
    t0 = time.time()

    for t in range(sc.n_tti):
        ch.advance()                # 1) 刷新快衰落（按相干时间）
        tr.step(t)                  # 2) 过期帧作废 + 新帧到达

        if t == warm:
            # 3) 预热结束：清零计数器，**同时丢掉在飞的帧**
            #    （否则会出现 ok = sent + 1 导致的 FSR > 100%）
            tr.reset_counters()
            bits = 0.0

        sinr = ch.sinr_db(active=active)                            # 4) 算 SINR
        grants = sch.schedule(sinr, link, tr.backlog_bytes,
                              tr.frame_backlog_bytes)               # 5) 分配 RB
        served = np.zeros(topo.n_ue)
        sizes = []
        for (ci, ues, n_rb) in grants:
            # 6) RB 数 -> 字节数；但不能超过该 UE 实际积压（否则会凭空造出流量）
            b = np.minimum(link.tb_bytes(n_rb, sinr[ues]), tr.backlog_bytes[ues])
            served[ues] += b
            sizes.append((ues, b))
            if topo.cell_centre[ci]:
                bits += float(b.sum()) * 8.0        # 只统计中心小区

        tr.serve(served)                            # 7) 喂给帧队列
        sch.update_rates(grants, sizes)             # 8) 更新 PF 历史速率

        if t % 200000 == 0 and t:
            el = time.time() - t0
            print(f"  [{args.ue}{args.scheme}s{args.seed}] {t}/{sc.n_tti} "
                  f"({el:.0f}s, {t/el:.0f} TTI/s)", flush=True)

    # 承载吞吐：只除以预热之后的时长，再除以中心小区数
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