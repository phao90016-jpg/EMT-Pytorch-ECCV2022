"""XR frame traffic, RTSR model updates and the 10 ms PDB (README section 6).

The discard rule is the paper's / ns-3's: when a new frame arrives, if the oldest SDU in
the buffer has already been waiting longer than the PDB, the arriving frame is dropped.
That is a head-of-line check on a FIFO in *time*.

`capacity_bytes_per_tti_per_ue` is the cell capacity shared out over the UEs; it sets how
much data can be drained within the PDB, i.e. the buffer depth at which arrivals start
being refused.  The runner passes it in from the measured cell capacity.
"""
import numpy as np


class Traffic:
    def __init__(self, sc, mode, topo, seed=None, capacity_mbps_per_cell=190.0):
        self.sc = sc
        self.mode = mode
        self.topo = topo
        rng = np.random.default_rng((seed if seed is not None else sc.seed) + 2000)
        self.rng = rng

        self.fps = 60.0
        self.frame_interval = 1.0 / self.fps
        self.pdb_tti = int(round(0.010 / sc.tti_s))

        self.bitrate_mbps = 20.0
        self.model_bytes_per_s = 0.0
        self.model_bytes_per_tti = 0.0

        # per-UE capacity share -> how many bytes drain within the PDB
        n_ue_cell = max(int(np.sum(topo.cell_ues[0] > -1)), 1)
        cap_bytes_per_tti = capacity_mbps_per_cell * 1e6 / 8.0 * sc.tti_s
        self.threshold = cap_bytes_per_tti / n_ue_cell * self.pdb_tti

        n = topo.n_ue
        # Frame bytes and model-update bytes are queued separately: only frame bytes
        # define the head-of-line wait (the model stream must not keep the buffer "busy").
        self.frame_backlog = np.zeros(n)
        self.model_backlog = np.zeros(n)
        self.hol_tti = np.full(n, -1, dtype=np.int64)
        self.next_arr_tti = np.zeros(n, dtype=np.int64)
        self.now_tti = 0
        self._schedule_next_arrival(np.arange(n), 0)

        self.frames_sent = np.zeros(n, dtype=np.int64)
        self.frames_ok = np.zeros(n, dtype=np.int64)

    # ------------------------------------------------------------- arrivals
    def _schedule_next_arrival(self, idx, now_tti):
        jitter = np.clip(self.rng.normal(0.0, 0.002, size=len(idx)), -0.004, 0.004)
        step = np.maximum(
            1, np.round((self.frame_interval + jitter) / self.sc.tti_s).astype(np.int64)
        )
        self.next_arr_tti[idx] = now_tti + step

    def _frame_bytes(self, n):
        mean = self.bitrate_mbps * 1e6 / 8.0 / self.fps
        return np.clip(self.rng.normal(mean, 0.105 * mean, size=n), 0.5 * mean, 1.5 * mean)

    # ------------------------------------------------------------- per TTI
    def step(self, now_tti):
        self.now_tti = now_tti
        if self.model_bytes_per_tti > 0:
            self.model_backlog += self.model_bytes_per_tti

        due = self.next_arr_tti <= now_tti
        if np.any(due):
            idx = np.flatnonzero(due)
            sizes = self._frame_bytes(len(idx))
            self.frames_sent[idx] += 1
            # head-of-line check: refuse the frame if the oldest queued byte is too old
            hol_wait = np.where(self.hol_tti[idx] >= 0,
                                now_tti - self.hol_tti[idx], 0)
            admit = hol_wait <= self.pdb_tti
            self._push(idx, np.where(admit, sizes, 0.0), now_tti)
            self.frames_ok[idx[admit]] += 1

            self._schedule_next_arrival(idx, now_tti)

    def _push(self, idx, add, now_tti):
        """Enqueue frame bytes for the UEs in `idx`, stamping the head-of-line time."""
        started = (self.frame_backlog[idx] <= 0) & (add > 0)
        self.hol_tti[idx[started]] = now_tti
        self.frame_backlog[idx] += add

    # ------------------------------------------------------------- service
    def serve(self, served_bytes):
        """Frame bytes are drained first, then model bytes."""
        b = served_bytes.copy()
        take = np.minimum(self.frame_backlog, b)
        self.frame_backlog -= take
        b -= take
        self.model_backlog = np.maximum(self.model_backlog - b, 0.0)
        empty = self.frame_backlog <= 0
        self.hol_tti[empty] = -1

    def drop_expired(self):
        self.frame_backlog = np.minimum(self.frame_backlog, 2.0 * 1024 * 1024)

    def reset_counters(self):
        self.frames_sent[:] = 0
        self.frames_ok[:] = 0

    @property
    def backlog_bytes(self):
        return self.frame_backlog + self.model_backlog
