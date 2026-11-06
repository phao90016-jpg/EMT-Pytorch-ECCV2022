"""Per-cell schedulers (README section 5.1 step 3).

`tdma`   : one UE per TTI (max-rate greedy), but only `rb_utilization` of the band is
           filled.  The ns-3 stage's TDMA-QoS scheduler issued ~2.5 TBs of ~29 RB per
           TTI, i.e. roughly a third of 273 RBs; that is what caps it at ~190 Mbps even
           though the link could carry ~290.
`ofdma_pf`: every RBG goes to the UE with the best proportional-fair metric, so the whole
           band is used every TTI - the regime the paper's numbers imply.
"""
import numpy as np


class Scheduler:
    def __init__(self, sc, mode, topo):
        self.sc = sc
        self.mode = mode
        self.topo = topo
        self.n_rb = sc.n_rb
        self.rbg_size = mode.rbg_size
        self.n_rbg = int(np.ceil(self.n_rb / self.rbg_size))
        self.rb_utilization = 0.5 if mode.scheduler == "tdma" else 1.0
        self.avg_rate = np.ones(topo.n_ue)

    def schedule(self, sinr_serving_db, link):
        """Return [(cell, ue_indices, rb_counts)] for this TTI."""
        grants = []
        for ci in range(self.topo.n_cells):
            ues = self.topo.cell_ues[ci]
            if len(ues) == 0:
                continue
            if self.mode.scheduler == "tdma":
                # greedy max-rate: the best UE in this TTI, like a real TDMA scheduler
                se = link.se(sinr_serving_db[ues])
                u = ues[int(np.argmax(se))]
                n_rb = max(1, int(round(self.rb_utilization * self.n_rb)))
                grants.append((ci, np.array([u]), np.array([n_rb])))
            else:
                grants.extend(self._ofdma_pf(ci, ues, sinr_serving_db, link))
        return grants

    def _ofdma_pf(self, ci, ues, sinr_db, link):
        rbg_rb = self.rbg_size
        se = link.se(sinr_db[ues])
        inst = se * rbg_rb * 12 * 12 / 8.0        # bytes if this UE got one RBG
        metric = inst / np.maximum(self.avg_rate[ues], 1e-9)

        alloc = np.zeros(len(ues), dtype=int)
        remaining = self.n_rbg
        while remaining > 0:
            k = int(np.argmax(metric))
            alloc[k] += 1
            metric[k] *= 0.5                       # diminishing returns within a TTI
            remaining -= 1
        sel = alloc > 0
        if not np.any(sel):
            return []
        return [(ci, ues[sel], alloc[sel] * rbg_rb)]

    def update_rates(self, grants, sizes_bytes):
        self.avg_rate = 0.99 * self.avg_rate
        for (ci, ues, n_rb), (u_sel, bytes_) in zip(grants, sizes_bytes):
            self.avg_rate[u_sel] += 0.01 * bytes_
