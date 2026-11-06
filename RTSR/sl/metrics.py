"""Per-UE frame success rate, satisfied ratio and capacity (README section 5.1 step 7)."""
import numpy as np


def fsr_per_ue(traffic):
    sent = np.maximum(traffic.frames_sent, 1)
    return traffic.frames_ok / sent


def summary(traffic, topo, cells_per_ue_cell):
    """Return a dict with the paper's two metrics over the *centre* UEs only."""
    m = topo.ue_is_centre
    fsr = fsr_per_ue(traffic)[m]
    sent = traffic.frames_sent[m]
    satisfied = fsr > 0.995
    return {
        "ues": int(m.sum()),
        "frames": int(sent.sum()),
        "mean_fsr_pct": float(100.0 * fsr.mean()) if len(fsr) else 0.0,
        "satisfied_pct": float(100.0 * satisfied.mean()) if len(fsr) else 0.0,
        "ue_per_cell": cells_per_ue_cell,
    }
