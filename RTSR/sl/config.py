"""Scenario and mode parameters - the single source of truth.

Nothing else in this package may hard-code a scenario number: if a value is needed twice
it lives here.  The two modes encode the ten "paper does not say" assumptions listed in
README.md section 2.
"""
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np


@dataclass
class Scenario:
    """Physical scenario, matching the ns-3 stage item by item (README section 4)."""

    # --- topology ---
    site_rings: int = 1            # 1 -> 7 sites -> 21 cells (the measured ones)
    interferer_rings: int = 1      # extra rings used only as interference (wraparound)
    isd_m: float = 200.0
    sectors: int = 3
    sector_bearings_deg: Tuple[float, ...] = (0.0, 120.0, 240.0)

    # --- radio ---
    fc_ghz: float = 4.0
    bw_mhz: float = 100.0
    scs_khz: float = 30.0
    tdd_dl_fraction: float = 0.7   # DDDSU: (3 DL + half of S) / 5
    tti_s: float = 0.5e-3
    gnb_power_dbm_per_20mhz: float = 44.0
    gnb_height_m: float = 25.0
    ue_height_m: float = 1.5
    nf_gnb_db: float = 5.0
    nf_ue_db: float = 9.0
    gnb_elements: int = 64         # 8x4 dual-polarised
    gnb_rows: int = 8
    gnb_cols: int = 4
    downtilt_deg: float = 12.0
    element_hpdbw_deg: float = 65.0
    element_vpdbw_deg: float = 65.0
    element_max_atten_db: float = 30.0

    # --- UEs ---
    ue_per_cell: int = 6
    indoor_ratio: float = 0.8
    indoor_penalty_db: float = 20.0
    ue_speed_kmh: float = 3.0

    # --- run ---
    duration_s: float = 1000.0
    seed: int = 1

    # ---- derived ----
    @property
    def n_rb(self) -> int:
        return int(self.bw_mhz * 1e6 / (self.scs_khz * 1e3 * 12))

    @property
    def cell_bandwidth_hz(self) -> float:
        return self.bw_mhz * 1e6

    @property
    def rb_bandwidth_hz(self) -> float:
        return self.cell_bandwidth_hz / self.n_rb

    @property
    def gnb_power_dbm(self) -> float:
        """Scale the paper's 44 dBm/20 MHz to the full bandwidth."""
        return self.gnb_power_dbm_per_20mhz + 10.0 * np.log10(self.bw_mhz / 20.0)

    @property
    def noise_dbm_per_rb(self) -> float:
        return (-174.0 + 10.0 * np.log10(self.rb_bandwidth_hz) + self.nf_ue_db)

    @property
    def noise_dbm_wideband(self) -> float:
        return (-174.0 + 10.0 * np.log10(self.cell_bandwidth_hz) + self.nf_ue_db)

    @property
    def n_tti(self) -> int:
        return int(round(self.duration_s / self.tti_s))


@dataclass
class Mode:
    """The ten assumptions of README section 2, as two presets."""

    name: str = "conservative"

    # 1 scheduler
    scheduler: str = "tdma"        # "tdma" | "ofdma_pf"
    rbg_size: int = 8              # RBs per resource block group
    # 2 beamforming
    ideal_beam: bool = False       # True: full array gain towards the served UE
    # 3 link abstraction
    use_3gpp_curves: bool = False  # False: SE table back-fitted from ns-3
    # 4 link adaptation
    olla: bool = False
    cqi_period_tti: int = 20
    # 5 indoor penetration
    o2i_model: bool = False        # True: 3GPP O2I, False: constant penalty
    # 6 model quality -> frame size
    model_feedback: bool = False   # True: mean = 20.8 kB * (2 - q)
    # 7/8 PDB handling
    pdb_granularity: str = "sdu"   # "sdu" | "frame"
    # 9 wraparound
    wraparound: bool = True
    # 10 seeds
    n_seeds: int = 1

    @staticmethod
    def conservative() -> "Mode":
        return Mode(name="conservative")

    @staticmethod
    def ideal() -> "Mode":
        return Mode(
            name="ideal",
            scheduler="ofdma_pf",
            ideal_beam=True,
            use_3gpp_curves=True,
            olla=True,
            o2i_model=True,
            model_feedback=True,
            pdb_granularity="frame",
            wraparound=True,
            n_seeds=3,
        )
