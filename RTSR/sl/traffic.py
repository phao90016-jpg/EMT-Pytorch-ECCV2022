"""XR frame traffic, RTSR model updates and the 10 ms PDB (README section 6).

Aggregate byte queue per UE, with the paper's discard rule expressed as a backlog
threshold: a frame arriving when the queue already holds more than `pdb_backlog_bytes`
has waited longer than the PDB, so it is dropped (and counted as a failure).  A frame that
is admitted is a success - its bytes do leave the queue.

`pdb_backlog_bytes` is the single calibrated constant of this model.  It is set so that
the three ns-3 reference points come out right (see calib_rb_util.py / check_m3.py):
6 UE/cell ~97%, 12 UE/cell ~3% for the conventional scheme.
"""
import numpy as np


class Traffic:
    # calibrated: how many bytes a cell can drain within the 10 ms PDB
    PDB_BACKLOG_BYTES = 200_000.0

    def __init__(self, sc, mode, topo, seed=None):
        self.sc = sc
        self.mode = mode
        self.topo = topo
        rng = np.random.default_rng((seed if seed is not None else sc.seed) + 2000)
        self.rng = rng

        self.fps = 60.0
        self.frame_interval = 1.0 / self.fps
        self.pdb_tti = int(round(0.010 / sc.tti_s))

        # conventional 20 Mbps pure video; RTSR 10 Mbps + paced model updates
        self.bitrate_mbps = 20.0
        self.model_bytes_per_s = 0.0
        self.model_bytes_per_tti = 0.0

        n = topo.n_ue
        self.backlog = np.zeros(n)
        self.next_arr_tti = np.zeros(n, dtype=np.int64)
        self.now_tti = 0
        self._schedule_next_arrival(np.arange(n), 0)

        self.frames_sent = np.zeros(n, dtype=np.int64)
        self.frames_ok = np.zeros(n, dtype=np.int64)
        self.model_bytes = np.zeros(n)
        self.threshold = float(self.PDB_BACKLOG_BYTES)

    # ------------------------------------------------------------- arrivals
    def _schedule_next_arrival(self, idx, now_tti):
        jitter = np.clip(self.rng.normal(0.0, 0.002, size=len(idx)), -0.004, 0.004)
        step = np.maximum(1, np.round((self.frame_interval + jitter) / self.sc.tti_s).astype(np.int64))
        self.next_arr_tti[idx] = now_tti + step

    def _frame_bytes(self, n):
        mean = self.bitrate_mbps * 1e6 / 8.0 / self.fps
        size = self.rng.normal(mean, 0.105 * mean, size=n)
        return np.clip(size, 0.5 * mean, 1.5 * mean)

    # ------------------------------------------------------------- per TTI
    def step(self, now_tti):
        self.now_tti = now_tti
        # model updates: a constant byte rate, added to the queue like data
        if self.model_bytes_per_tti > 0:
            self.backlog += self.model_bytes_per_tti
            self.model_bytes += self.model_bytes_per_tti

        due = self.next_arr_tti <= now_tti
        if np.any(due):
            idx = np.flatnonzero(due)
            sizes = self._frame_bytes(len(idx))
            self.frames_sent[idx] += 1
            # Partial admission, like the per-SDU discard of the ns-3 stage: whatever fits
            # under the PDB threshold enters the buffer, the rest is dropped.  The frame
            # only counts as a success if *all* of it was admitted.
            room = np.maximum(self.threshold - self.backlog[idx], 0.0)
            admit = np.minimum(room, sizes)
            self.backlog[idx] += admit
            complete = admit >= sizes - 1e-9
            self.frames_ok[idx[complete]] += 1
            self._schedule_next_arrival(idx, now_tti)

    # ------------------------------------------------------------- service
    def serve(self, served_bytes):
        self.backlog = np.maximum(self.backlog - served_bytes, 0.0)

    def drop_expired(self):
        """Bytes in the queue live in the buffer; the RLC cap is 2 MiB in the ns-3 stage."""
        self.backlog = np.minimum(self.backlog, 2.0 * 1024 * 1024)

    def reset_counters(self):
        self.frames_sent[:] = 0
        self.frames_ok[:] = 0

    @property
    def backlog_bytes(self):
        return self.backlog
