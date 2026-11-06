"""Hexagonal layout, wraparound, UE drop and mobility (README section 5).

UEs are dropped in *every* cell; the outer rings exist so that neighbour interference is
real (a cell with no UE never transmits).  Only the centre cells' UEs enter the statistics.
"""
from dataclasses import dataclass
from typing import Tuple

import numpy as np


def hex_axial_coords(rings: int) -> np.ndarray:
    """All axial (q, r) within `rings`: 0 -> 1 site, 1 -> 7, 2 -> 19, 3 -> 37."""
    out = []
    for q in range(-rings, rings + 1):
        for r in range(-rings, rings + 1):
            if abs(q + r) <= rings:
                out.append((q, r))
    return np.array(out, dtype=np.int32)


def axial_to_xy(coords: np.ndarray, isd_m: float) -> np.ndarray:
    """Nearest-neighbour distance of the resulting lattice equals `isd_m`."""
    q = coords[:, 0].astype(float)
    r = coords[:, 1].astype(float)
    x = isd_m * (q + r / 2.0)
    y = isd_m * (np.sqrt(3.0) / 2.0 * r)
    return np.stack([x, y], axis=1)


def wrap_to_pi(a: np.ndarray) -> np.ndarray:
    return (a + np.pi) % (2.0 * np.pi) - np.pi


@dataclass
class Site:
    xy: np.ndarray
    is_centre: bool


@dataclass
class Cell:
    site_idx: int
    sector: int
    bearing_rad: float
    xy: np.ndarray
    is_centre: bool


class Topology:
    """Centre cells are measured; outer cells carry traffic so that they interfere."""

    def __init__(self, sc):
        self.sc = sc
        rng = np.random.default_rng(sc.seed)

        total_rings = sc.site_rings + sc.interferer_rings
        coords = hex_axial_coords(total_rings)
        xy = axial_to_xy(coords, sc.isd_m)
        centre_mask = np.array(
            [max(abs(q), abs(r), abs(q + r)) <= sc.site_rings for q, r in coords]
        )
        self.sites = [Site(xy[i], bool(centre_mask[i])) for i in range(len(coords))]

        # three sectors per site, each 1 m off the site centre (as in the ns-3 stage)
        self.cells = []
        offset = 1.0
        for i, site in enumerate(self.sites):
            for s in range(sc.sectors):
                b = np.deg2rad(sc.sector_bearings_deg[s])
                cxy = site.xy + offset * np.array([np.cos(b), np.sin(b)])
                self.cells.append(Cell(i, s, b, cxy, site.is_centre))
        self.cell_xy = np.array([c.xy for c in self.cells])
        self.cell_centre = np.array([c.is_centre for c in self.cells])
        self.n_cells = len(self.cells)
        self.cell_bearing = np.array([c.bearing_rad for c in self.cells])

        self._drop_ues(rng)

    # ------------------------------------------------------------------ UEs
    def _drop_ues(self, rng):
        """k UEs per cell inside the sector wedge (same rule as the ns-3 stage)."""
        sc = self.sc
        k = sc.ue_per_cell
        xs, cells, indoor = [], [], []
        for ci in range(self.n_cells):
            cell = self.cells[ci]
            az = cell.bearing_rad + rng.uniform(-np.pi / 3, np.pi / 3, size=k)
            rad = rng.uniform(0.0, sc.isd_m / 2.0, size=k)
            pts = cell.xy + np.stack([rad * np.cos(az), rad * np.sin(az)], axis=1)
            xs.append(pts)
            cells.append(np.full(k, ci))
            indoor.append(rng.random(k) < sc.indoor_ratio)
        self.ue_xy = np.concatenate(xs, axis=0)
        self.ue_cell = np.concatenate(cells)
        self.ue_indoor = np.concatenate(indoor)
        self.n_ue = len(self.ue_cell)
        self.ue_is_centre = self.cell_centre[self.ue_cell]
        self.ue_speed = sc.ue_speed_kmh / 3.6
        self.ue_heading = rng.uniform(-np.pi, np.pi, size=self.n_ue)

        # cell -> UE index lists, used by the scheduler
        order = np.argsort(self.ue_cell, kind="stable")
        self.cell_ues = np.split(order, np.cumsum(np.bincount(self.ue_cell))[:-1])

    def move(self, dt_s: float):
        v = self.ue_speed * dt_s
        self.ue_xy = self.ue_xy + v * np.stack(
            [np.cos(self.ue_heading), np.sin(self.ue_heading)], axis=1
        )

    # ------------------------------------------------------------------ helpers
    def distances(self) -> np.ndarray:
        d = self.ue_xy[:, None, :] - self.cell_xy[None, :, :]
        return np.linalg.norm(d, axis=2)

    def azimuths(self) -> np.ndarray:
        d = self.ue_xy[:, None, :] - self.cell_xy[None, :, :]
        return np.arctan2(d[:, :, 1], d[:, :, 0])
