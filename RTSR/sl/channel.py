"""Path loss, shadowing, penetration, beam gain, activity and SINR (README section 5.1).

The static part (path loss + shadowing + beam) is precomputed once; only the fast fading
and the per-TTI cell activity are refreshed during the run.  At 3 km/h and 4 GHz the
Doppler spread is ~11 Hz (coherence time ~45 ms), so refreshing the fading every 90 TTIs
is enough and keeps the run cheap.
"""
import numpy as np

from .topology import Topology, wrap_to_pi


class Channel:
    def __init__(self, sc, mode, topo: Topology, load_per_cell_mbps: float = None):
        self.sc = sc
        self.mode = mode
        self.topo = topo
        rng = np.random.default_rng(sc.seed + 1000)

        d2 = topo.distances()
        h = sc.gnb_height_m - sc.ue_height_m
        self.d3 = np.sqrt(d2 ** 2 + h ** 2)
        los = self._los_probability(self.d3) > rng.random(self.d3.shape)
        self.los = los
        self.path_loss_db = np.where(los, self._pl_los(self.d3), self._pl_nlos(self.d3))

        sigma = np.where(los, 4.0, 6.0)
        self.shadow_db = rng.normal(0.0, 1.0, self.d3.shape) * sigma

        # Indoor penetration is always a *distribution* (TR 38.901 7.4.3: wall loss plus a
        # term proportional to the indoor depth).  The ideal mode uses the low-loss wall
        # (10 dB); the conservative mode uses the high-loss one (20 dB) but still varies
        # the depth, because a flat penalty puts every indoor UE at the same disadvantage
        # and creates an artificial SINR low tail that no scheduling can recover.
        depth = rng.uniform(0.0, 25.0, self.d3.shape)      # metres inside the building
        wall = 10.0 if mode.o2i_model else sc.indoor_penalty_db
        pen = wall + 0.5 * depth
        pen = np.where(topo.ue_indoor[:, None], pen, 0.0)
        self.penetration_db = pen

        self.beam_gain_db = self._beam_gain()

        # ---- cell activity: fraction of TTIs in which a cell has data to send ----
        # In the system-level stage the scheduler provides the real activity; until then
        # derive it from the offered load (this is what makes SINR depend on UE density).
        if load_per_cell_mbps is None:
            load_per_cell_mbps = sc.ue_per_cell * 20.0
        self.activity = float(np.clip(load_per_cell_mbps / 190.0, 0.02, 1.0))
        self._rng = rng

        # static received power (path loss + shadowing + penetration + beam): computed
        # once, never changes during the run
        self._p_rx_static = (sc.gnb_power_dbm
                             - self.path_loss_db
                             - self.shadow_db
                             - self.penetration_db
                             + self.beam_gain_db)

        self._fading = None
        self._p_lin = None                 # cached linear power matrix
        self.coherence_tti = max(1, int(round(0.045 / sc.tti_s)))
        self.refresh_fading()
        self.tti_count = 0

    # ---------------------------------------------------------------- models
    @staticmethod
    def _los_probability(d_m: np.ndarray) -> np.ndarray:
        d = np.maximum(d_m, 1.0)
        p = np.where(d <= 18.0, 1.0, 18.0 / d + np.exp(-d / 63.0) * (1.0 - 18.0 / d))
        return np.clip(p, 0.0, 1.0)

    def _pl_los(self, d_m: np.ndarray) -> np.ndarray:
        fc = self.sc.fc_ghz
        h_bs, h_ut = self.sc.gnb_height_m, self.sc.ue_height_m
        d_bp = 4.0 * (h_bs - 1.0) * (h_ut - 1.0) * (fc * 1e9) / 3e8
        d = np.maximum(d_m, 10.0)
        pl1 = 28.0 + 22.0 * np.log10(d) + 20.0 * np.log10(fc)
        pl2 = (28.0 + 40.0 * np.log10(d) + 20.0 * np.log10(fc)
               - 9.0 * np.log10(d_bp ** 2 + (h_bs - h_ut) ** 2))
        return np.where(d <= d_bp, pl1, pl2)

    def _pl_nlos(self, d_m: np.ndarray) -> np.ndarray:
        fc = self.sc.fc_ghz
        d = np.maximum(d_m, 10.0)
        return (13.54 + 39.08 * np.log10(d) + 20.0 * np.log10(fc)
                - 0.6 * (self.sc.ue_height_m - 1.5))

    def _element_pattern_db(self, az_off, el_off) -> np.ndarray:
        sc = self.sc
        ah = -np.minimum(12.0 * (np.degrees(az_off) / sc.element_hpdbw_deg) ** 2,
                         sc.element_max_atten_db)
        av = -np.minimum(12.0 * (np.degrees(el_off) / sc.element_vpdbw_deg) ** 2,
                         sc.element_max_atten_db)
        return ah + av

    def _beam_gain(self) -> np.ndarray:
        """(n_ue, n_cells) beam gain in dB.

        The serving cell steers its beam to the UE: element pattern 0 dB at boresight plus
        the array factor 10log10(N).  A neighbour's beam points at *its own* UE, so towards
        this UE only the element pattern applies (standard system-level approximation).
        """
        sc, topo = self.sc, self.topo
        az = topo.azimuths()
        d = topo.distances()
        elev = np.arctan2(-(sc.gnb_height_m - sc.ue_height_m), np.maximum(d, 1.0))
        bearings = np.array([c.bearing_rad for c in topo.cells])[None, :]
        off = np.abs(wrap_to_pi(az - bearings))
        gain = self._element_pattern_db(off, elev + np.deg2rad(sc.downtilt_deg))

        array_db = 10.0 * np.log10(sc.gnb_elements)
        # exact steering: the serving link sees boresight (0 dB) plus the array factor,
        # not the off-boresight element attenuation
        gain = gain.copy()
        gain[np.arange(topo.n_ue), topo.ue_cell] = array_db
        return gain

    # ---------------------------------------------------------------- fading
    def refresh_fading(self, rng=None):
        rng = self._rng if rng is None else rng
        shape = self.d3.shape
        re = rng.normal(size=shape) / np.sqrt(2.0)
        im = rng.normal(size=shape) / np.sqrt(2.0)
        self._fading = re ** 2 + im ** 2          # mean power 1 (0 dB)
        # linear power matrix for this fading realisation; reused until the next refresh
        self._p_lin = 10.0 ** ((self._p_rx_static
                                + 10.0 * np.log10(self._fading + 1e-12)) / 10.0)

    def advance(self):
        self.tti_count += 1
        if self.tti_count % self.coherence_tti == 0:
            self.refresh_fading()

    # ---------------------------------------------------------------- SINR
    def rx_power_dbm(self) -> np.ndarray:
        return (self.sc.gnb_power_dbm
                - self.path_loss_db
                - self.shadow_db
                - self.penetration_db
                + self.beam_gain_db)

    def sinr_db(self, active: np.ndarray = None) -> np.ndarray:
        """Wideband SINR per UE.

        `active` is a boolean (n_cells,) mask of cells transmitting in this TTI.  If None,
        every cell is active (upper bound on interference).  Uses the cached linear power
        matrix, so the per-TTI cost is one matrix-vector product.
        """
        p_lin = self._p_lin
        served = self.topo.ue_cell
        idx = np.arange(self.topo.n_ue)

        if active is None:
            active = np.ones(self.topo.n_cells, dtype=bool)
        act = active.astype(float)

        p_serv = p_lin[idx, served]
        total = p_lin @ act                       # BLAS mat-vec over the cell dimension
        interf = np.maximum(total - p_serv, 0.0)
        noise = 10.0 ** (self.sc.noise_dbm_wideband / 10.0)
        sinr = p_serv / (interf + noise)
        return 10.0 * np.log10(sinr + 1e-12)

    def sample_activity(self, rng=None, override: float = None) -> np.ndarray:
        rng = self._rng if rng is None else rng
        a = self.activity if override is None else override
        return rng.random(self.topo.n_cells) < a
