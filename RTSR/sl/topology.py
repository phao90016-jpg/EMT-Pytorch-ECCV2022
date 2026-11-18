"""六边形站址布局、wraparound、终端撒点与移动（README 第 5 节）。

**关键设计**：终端撒在**每一个**小区里，包括外圈。
外圈存在的唯一目的是让邻区干扰真实存在——一个没有终端的小区永远不会发射，
那样统计出来的 SINR 会过于乐观。统计只取中心小区的那批终端。
"""
from dataclasses import dataclass
from typing import Tuple

import numpy as np


def hex_axial_coords(rings: int) -> np.ndarray:
    """返回半径 `rings` 内所有六边形站址的轴向坐标 (q, r)。

    圈数与站数：0 圈 -> 1 站，1 圈 -> 7 站，2 圈 -> 19 站，3 圈 -> 37 站。
    判断标准是六边形距离 max(|q|, |r|, |q+r|)。
    """
    out = []
    for q in range(-rings, rings + 1):
        for r in range(-rings, rings + 1):
            if abs(q + r) <= rings:
                out.append((q, r))
    return np.array(out, dtype=np.int32)


def axial_to_xy(coords: np.ndarray, isd_m: float) -> np.ndarray:
    """把轴向坐标换成笛卡尔坐标，使最近邻间距正好等于 `isd_m`。"""
    q = coords[:, 0].astype(float)
    r = coords[:, 1].astype(float)
    x = isd_m * (q + r / 2.0)
    y = isd_m * (np.sqrt(3.0) / 2.0 * r)
    return np.stack([x, y], axis=1)


def wrap_to_pi(a: np.ndarray) -> np.ndarray:
    """把角度折到 (-pi, pi]，用于方位角相减。"""
    return (a + np.pi) % (2.0 * np.pi) - np.pi


@dataclass
class Site:
    """一个站址：位置 + 是否属于中心（参与统计）的那一圈。"""

    xy: np.ndarray
    is_centre: bool


@dataclass
class Cell:
    """一个小区（= 一个扇区）：所属站、扇区号、朝向、天线位置、是否中心。"""

    site_idx: int
    sector: int
    bearing_rad: float
    xy: np.ndarray
    is_centre: bool


class Topology:
    """中心小区参与统计；外圈小区也承载流量，因此会真实地产生干扰。"""

    def __init__(self, sc):
        self.sc = sc
        rng = np.random.default_rng(sc.seed)

        # 站址 = 中心圈 + 若干圈纯干扰站
        total_rings = sc.site_rings + sc.interferer_rings
        coords = hex_axial_coords(total_rings)
        xy = axial_to_xy(coords, sc.isd_m)
        # 六边形距离 <= site_rings 的站算"中心"，只有它们的终端进统计
        centre_mask = np.array(
            [max(abs(q), abs(r), abs(q + r)) <= sc.site_rings for q, r in coords]
        )
        self.sites = [Site(xy[i], bool(centre_mask[i])) for i in range(len(coords))]

        # 每站 3 个扇区，扇区天线偏离站心 1 米（与 ns-3 阶段保持一致）
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

    # ------------------------------------------------------------------ 终端
    def _drop_ues(self, rng):
        """每小区撒 k 个终端，限定在扇区楔形内（与 ns-3 阶段的规则一致）。

        方位角在 [bearing-60°, bearing+60°] 内均匀，距离在 [0, isd/2] 内均匀。
        室内/室外按 indoor_ratio 随机划分。
        """
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
        self.ue_speed = sc.ue_speed_kmh / 3.6          # km/h -> m/s
        self.ue_heading = rng.uniform(-np.pi, np.pi, size=self.n_ue)

        # 小区 -> 该小区终端索引列表，调度器按小区取用
        order = np.argsort(self.ue_cell, kind="stable")
        self.cell_ues = np.split(order, np.cumsum(np.bincount(self.ue_cell))[:-1])

    def move(self, dt_s: float):
        """直线匀速移动（不建模切换，见偏差 #13）。"""
        v = self.ue_speed * dt_s
        self.ue_xy = self.ue_xy + v * np.stack(
            [np.cos(self.ue_heading), np.sin(self.ue_heading)], axis=1
        )

    # ------------------------------------------------------------------ 几何辅助
    def distances(self) -> np.ndarray:
        """返回 (n_ue, n_cells) 的距离矩阵，单位米。"""
        d = self.ue_xy[:, None, :] - self.cell_xy[None, :, :]
        return np.linalg.norm(d, axis=2)

    def azimuths(self) -> np.ndarray:
        """返回 (n_ue, n_cells) 的方位角矩阵（弧度，终端相对小区天线的方向）。"""
        d = self.ue_xy[:, None, :] - self.cell_xy[None, :, :]
        return np.arctan2(d[:, :, 1], d[:, :, 0])