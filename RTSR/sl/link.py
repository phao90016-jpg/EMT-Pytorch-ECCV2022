"""SINR -> spectral efficiency -> transport block size (README section 5.1 step 4).

Shannon-style bound with a coding gap, capped at the 256QAM rate (7.4 bits/RE):
    SE = alpha * log2(1 + SINR / gap)      clipped to SE_MAX

  * conservative: alpha=0.75, gap=3 dB  (implementation margin, matches the ns-3 stage)
  * ideal       : alpha=0.85, gap=0 dB  (optimistic end of a 3GPP link-level curve)

`single layer` is assumed (64T4R with 1 layer).  Multi-layer MIMO is a knob for later.
"""
import numpy as np


class Link:
    SE_MAX = 7.4063          # 256QAM, code rate ~0.93

    def __init__(self, sc, mode):
        self.sc = sc
        self.mode = mode
        if mode.use_3gpp_curves:
            self.alpha, self.gap_db = 0.85, 0.0
        else:
            self.alpha, self.gap_db = 0.75, 3.0
        self.n_layers = 1

    def se(self, sinr_db) -> np.ndarray:
        sinr_lin = 10.0 ** (np.asarray(sinr_db) / 10.0)
        gap = 10.0 ** (self.gap_db / 10.0)
        se = self.alpha * np.log2(1.0 + sinr_lin / gap) * self.n_layers
        return np.minimum(se, self.SE_MAX * self.n_layers)

    def tb_bytes(self, n_rb, sinr_db) -> np.ndarray:
        """Bytes carried by a grant of `n_rb` RBs at the given SINR."""
        n_re = np.asarray(n_rb) * 12 * 12      # 12 subcarriers x 12 data symbols
        return n_re * self.se(sinr_db) / 8.0
