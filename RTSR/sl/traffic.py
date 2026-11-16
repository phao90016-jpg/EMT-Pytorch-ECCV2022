"""XR frame traffic, RTSR model updates and the 10 ms PDB (README section 6).

PDB semantics are selected by `mode.pdb_granularity`:

* ``"frame"`` (paper / ns-3, used by the ideal mode): every frame carries its own
  deadline.  A frame is *successful* only if all of its bytes are served before
  ``arrival + 10 ms``; otherwise it is dropped and counts as a failure.  This is the
  same definition as ``complete / sent`` in the ns-3 stage and in the paper
  ("if the waiting time of the frame at BS buffer exceeds 10ms, it will be dropped").
* ``"sdu"`` (legacy): when a frame arrives, the arriving frame is refused if the oldest
  byte already queued has waited longer than the PDB, and *admission* counts as success.
  That is an admission rate, not a delivery rate, and it is kept only so the old
  conservative-mode calibrations can still be reproduced.

Frame bytes and model-update bytes are queued separately: only frame bytes define the
head-of-line wait, so the paced model stream cannot keep the video queue "busy".
"""
import numpy as np

# At most this many frames can be in flight per UE.  With a 10 ms PDB and a 16.7 ms
# frame interval at most two are ever queued, so 4 is generous and keeps the per-TTI
# work vectorised over a fixed (n_ue, SLOTS) array.
SLOTS = 4


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
        self.frame_level = (getattr(mode, "pdb_granularity", "sdu") == "frame")

        self.bitrate_mbps = 20.0
        self.model_bytes_per_s = 0.0
        self.model_bytes_per_tti = 0.0

        n = topo.n_ue
        self.n_ue = n

        # --- frame queue: (n_ue, SLOTS) ---
        self.frame_rem = np.zeros((n, SLOTS))
        self.frame_deadline = np.zeros((n, SLOTS), dtype=np.int64)
        self.frame_alive = np.zeros((n, SLOTS), dtype=bool)

        # legacy admission bookkeeping (only used when frame_level is False)
        self.hol_tti = np.full(n, -1, dtype=np.int64)

        self.model_backlog = np.zeros(n)
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

        # 1) expire frames whose own deadline has passed (paper: wait > PDB -> drop)
        if self.frame_level:
            expired = self.frame_alive & (now_tti > self.frame_deadline)
            if np.any(expired):
                self.frame_alive[expired] = False
                self.frame_rem[expired] = 0.0

        # 2) arrivals
        due = self.next_arr_tti <= now_tti
        if np.any(due):
            idx = np.flatnonzero(due)
            sizes = self._frame_bytes(len(idx))
            self.frames_sent[idx] += 1

            if self.frame_level:
                free = ~self.frame_alive[idx]
                has = free.any(axis=1)
                slot = free.argmax(axis=1)
                sel = idx[has]
                self.frame_alive[sel, slot[has]] = True
                self.frame_rem[sel, slot[has]] = sizes[has]
                self.frame_deadline[sel, slot[has]] = now_tti + self.pdb_tti
                # frames with no free slot are dropped immediately (never successful)
            else:
                hol_wait = np.where(self.hol_tti[idx] >= 0, now_tti - self.hol_tti[idx], 0)
                admit = hol_wait <= self.pdb_tti
                self.frames_ok[idx[admit]] += 1
                self._push_legacy(idx, np.where(admit, sizes, 0.0), now_tti)

            self._schedule_next_arrival(idx, now_tti)

    def _push_legacy(self, idx, add, now_tti):
        backlog = self.frame_rem[idx].sum(axis=1)
        started = (backlog <= 0) & (add > 0)
        self.hol_tti[idx[started]] = now_tti
        free = ~self.frame_alive[idx]
        has = free.any(axis=1) & (add > 0)
        slot = free.argmax(axis=1)
        sel = idx[has]
        self.frame_alive[sel, slot[has]] = True
        self.frame_rem[sel, slot[has]] = add[has]
        self.frame_deadline[sel, slot[has]] = now_tti + self.pdb_tti

    # ------------------------------------------------------------- service
    def serve(self, served_bytes):
        """Drain frame bytes (earliest deadline first), then model bytes."""
        avail = served_bytes.copy()
        rows = np.arange(self.n_ue)
        # earliest deadline first == FIFO here, because deadline = arrival + const
        order = np.argsort(
            np.where(self.frame_alive, self.frame_deadline, np.iinfo(np.int64).max), axis=1
        )
        for j in range(SLOTS):
            k = order[:, j]
            need = self.frame_rem[rows, k]
            if not np.any(need > 0):
                continue
            take = np.minimum(need, avail)
            self.frame_rem[rows, k] -= take
            avail -= take
            if self.frame_level:
                done = self.frame_alive[rows, k] & (self.frame_rem[rows, k] <= 1e-9)
                if np.any(done):
                    self.frames_ok[rows[done]] += 1
                    self.frame_alive[rows[done], k[done]] = False
            else:
                emptied = self.frame_rem[rows, k] <= 1e-9
                if np.any(emptied):
                    self.frame_alive[rows[emptied], k[emptied]] = False
                    self.hol_tti[rows[emptied]] = -1

        self.model_backlog = np.maximum(self.model_backlog - avail, 0.0)

    def drop_expired(self):
        """Kept for API compatibility; expiry is handled inside step()."""

    def reset_counters(self):
        """Zero the counters AND drop in-flight frames.

        A frame that arrived before the warm-up boundary would otherwise have its
        `frames_sent` zeroed while its completion still increments `frames_ok`, which
        showed up as FSR > 100% (ok = sent + 1) on the fastest UEs.
        """
        self.frames_sent[:] = 0
        self.frames_ok[:] = 0
        self.frame_alive[:] = False
        self.frame_rem[:] = 0.0
        self.model_backlog[:] = 0.0
        self.hol_tti[:] = -1

    # ------------------------------------------------------------- views
    @property
    def frame_backlog_bytes(self):
        return self.frame_rem.sum(axis=1)

    @property
    def backlog_bytes(self):
        return self.frame_backlog_bytes + self.model_backlog