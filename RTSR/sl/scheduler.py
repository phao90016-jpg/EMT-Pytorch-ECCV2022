"""Per-cell schedulers (README section 5.1 step 3).

Both modes use a proportional-fair metric (fairness matters as soon as there is real
traffic: a greedy max-rate scheduler starves all but one UE per cell, which is nothing like
the paper's or the ns-3 stage's behaviour).

`tdma`   : one UE per TTI (PF), but only `rb_utilization` of the band is filled.  The ns-3
           stage's TDMA-QoS scheduler issued ~2.5 TBs of ~29 RB per TTI, i.e. roughly a
           third of the 273 RBs; that is what caps it at ~190 Mbps.
`ofdma_pf`: every RBG goes to the best PF user, so the whole band is used every TTI.
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
        # calibrated so that the conservative mode reproduces the ns-3 stage's ~190 Mbps
        self.rb_utilization = 0.60 if mode.scheduler == "tdma" else 1.0
        self.avg_rate = np.ones(topo.n_ue)
        self.decay = 0.98

    # ------------------------------------------------------------------ main
    def schedule(self, sinr_db, link, backlog_bytes):
        """Return [(cell, ue_indices, rb_counts)] for this TTI."""
        grants = []
        for ci in range(self.topo.n_cells):
            ues = self.topo.cell_ues[ci]
            if len(ues) == 0:
                continue
            ues = ues[backlog_bytes[ues] > 0.0]        # only UEs with data
            if len(ues) == 0:
                continue
            if self.mode.scheduler == "tdma":
                se = link.se(sinr_db[ues])
                inst = se * self.rb_utilization * self.n_rb * 12 * 12 / 8.0
                metric = inst / np.maximum(self.avg_rate[ues], 1e-9)
                u = ues[int(np.argmax(metric))]
                n_rb = max(1, int(round(self.rb_utilization * self.n_rb)))
                grants.append((ci, np.array([u]), np.array([n_rb])))
            else:
                grants.extend(self._ofdma_pf(ci, ues, sinr_db, link))
        return grants

    # ------------------------------------------------------------------ PF
    def _ofdma_pf(self, ci, ues, sinr_db, link):
        rbg_rb = self.rbg_size
        se = link.se(sinr_db[ues])
        inst = se * rbg_rb * 12 * 12 / 8.0
        metric = inst / np.maximum(self.avg_rate[ues], 1e-9)

        alloc = np.zeros(len(ues), dtype=int)
        remaining = self.n_rbg
        while remaining > 0:
            k = int(np.argmax(metric))
            alloc[k] += 1
            metric[k] *= 0.5
            remaining -= 1
        sel = alloc > 0
        if not np.any(sel):
            return []
        return [(ci, ues[sel], alloc[sel] * rbg_rb)]

    def update_rates(self, grants, sizes_bytes):
        self.avg_rate *= self.decay
        for (ci, ues, n_rb), (u_sel, bytes_) in zip(grants, sizes_bytes):
            self.avg_rate[u_sel] += (1.0 - self.decay) * bytes_
