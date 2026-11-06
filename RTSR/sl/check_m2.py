#!/usr/bin/env python3
"""M2 check: with every UE backlogged, how much can one cell carry?

Targets (README section 3, after the TDD DL factor is applied):
  conservative : ~190 Mbps/cell  (ns-3 measured 191 Mbps at 12 UE/cell)
  ideal        : 300-420 Mbps/cell (paper implies ~350)
"""
import sys

import numpy as np

sys.path.insert(0, "/home/penghao/code/EMT-Pytorch-ECCV2022/RTSR")

from sl.config import Mode, Scenario  # noqa: E402
from sl.topology import Topology  # noqa: E402
from sl.channel import Channel  # noqa: E402
from sl.link import Link  # noqa: E402
from sl.scheduler import Scheduler  # noqa: E402


def capacity(mode, ue_per_cell=12, n_tti=400, seed=1):
    sc = Scenario(ue_per_cell=ue_per_cell, seed=seed)
    topo = Topology(sc)
    ch = Channel(sc, mode, topo, load_per_cell_mbps=ue_per_cell * 20.0)
    link = Link(sc, mode)
    sch = Scheduler(sc, mode, topo)

    active = np.array([len(topo.cell_ues[ci]) > 0 for ci in range(topo.n_cells)])
    bits_centre = 0.0
    se_acc, rb_acc, n_c, ue_c = 0.0, 0.0, 0, 0
    n_centre = int(topo.cell_centre.sum())
    for _ in range(n_tti):
        ch.advance()
        sinr = ch.sinr_db(active=active)
        grants = sch.schedule(sinr, link)
        sizes = []
        for (ci, ues, n_rb) in grants:
            b = link.tb_bytes(n_rb, sinr[ues])
            sizes.append((ues, b))
            if topo.cell_centre[ci]:
                bits_centre += b.sum() * 8.0
                se_acc += float(link.se(sinr[ues]).sum())
                ue_c += len(ues)
                rb_acc += float(np.sum(n_rb))
                n_c += 1
        sch.update_rates(grants, sizes)

    seconds = n_tti * sc.tti_s
    dl = sc.tdd_dl_fraction
    mbps_per_cell = bits_centre / seconds / max(n_centre, 1) / 1e6 * dl
    return mbps_per_cell, se_acc / max(ue_c, 1), rb_acc / max(n_c, 1), sch.rb_utilization


def main():
    print("=== M2 check: single-cell capacity (all UEs backlogged, TDD 70% applied) ===\n")
    c, se_c, rb_c, u_c = capacity(Mode.conservative())
    print(f"conservative (tdma,  rb_util={u_c:.2f}): {c:6.1f} Mbps/cell  "
          f"[mean SE {se_c:.2f} b/RE, {rb_c:.0f} RB/TTI]   target 190 +/- 25")
    i, se_i, rb_i, u_i = capacity(Mode.ideal())
    print(f"ideal        (ofdma, rb_util={u_i:.2f}): {i:6.1f} Mbps/cell  "
          f"[mean SE {se_i:.2f} b/RE, {rb_i:.0f} RB/TTI]   target 300-420")

    ok_c = abs(c - 190.0) <= 25.0
    ok_i = 300.0 <= i <= 420.0
    print(f"\n  conservative: {'PASS' if ok_c else 'FAIL'}")
    print(f"  ideal       : {'PASS' if ok_i else 'FAIL'}")
    return 0 if (ok_c and ok_i) else 1


if __name__ == "__main__":
    sys.exit(main())
