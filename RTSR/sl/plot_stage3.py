#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-3 Fig.5 / Fig.6 from the 60 s quick-validation sweep (57 cells, icic 16 dB).

Input : RTSR/sl/results/quick_icic16.csv   (ue,scheme,satisfied_pct,mean_fsr_pct)
Output: RTSR/docs/figs/stage3_quick.png

The 1000 s x 3-seed M6 dataset supersedes this for the formal claim; this figure exists so
the stage-3 conclusions can be shown before M6 finishes (and to keep the old, now invalid
m6_fig5.png from being read as current).
"""
import csv
import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))          # .../RTSR/sl
REPO = os.path.dirname(HERE)                                # .../RTSR
CSV = os.path.join(REPO, "sl", "results", "quick_icic16.csv")
OUT = os.path.join(REPO, "docs", "figs", "stage3_quick.png")


def load():
    d = {"conv": {"ue": [], "sat": [], "fsr": []},
         "rtsr": {"ue": [], "sat": [], "fsr": []}}
    with io.open(CSV, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            k = r["scheme"].strip()
            d[k]["ue"].append(int(r["ue"]))
            d[k]["sat"].append(float(r["satisfied_pct"]))
            d[k]["fsr"].append(float(r["mean_fsr_pct"]))
    for v in d.values():
        o = sorted(range(len(v["ue"])), key=lambda i: v["ue"][i])
        for key in ("ue", "sat", "fsr"):
            v[key] = [v[key][i] for i in o]
    return d


def main():
    d = load()
    style = {
        "conv": dict(color="#c0392b", marker="o", lw=2, ms=8, label="Conventional 20 Mbps"),
        "rtsr": dict(color="#2471a3", marker="s", lw=2, ms=8, label="RTSR 10 Mbps + model"),
    }
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.8))

    for k in ("conv", "rtsr"):
        v = d[k]
        if not v["ue"]:
            continue
        a1.plot(v["ue"], v["sat"], **style[k])
        for x, y in zip(v["ue"], v["sat"]):
            a1.annotate("%.1f" % y, (x, y), textcoords="offset points",
                        xytext=(0, 10 if k == "rtsr" else -16), ha="center",
                        fontsize=8.5, color=style[k]["color"])
        a2.plot(v["ue"], v["fsr"], **style[k])
        for x, y in zip(v["ue"], v["fsr"]):
            a2.annotate("%.1f" % y, (x, y), textcoords="offset points",
                        xytext=(0, 9 if k == "rtsr" else -15), ha="center",
                        fontsize=8.5, color=style[k]["color"])

    a1.axhline(90, color="gray", ls="--", lw=1)
    a1.text(15.0, 91.2, "90% criterion", fontsize=8.5, color="gray")
    a1.set_xlabel("UE per cell")
    a1.set_ylabel("Satisfied UEs (%)  [per-UE FSR > 99.5%]")
    a1.set_title("Fig.5  Satisfied UE ratio (60 s quick validation)")
    a1.set_ylim(60, 102)
    a1.grid(alpha=0.3)

    a2.axhline(99.5, color="gray", ls="--", lw=1)
    a2.text(15.0, 99.55, "per-UE threshold 99.5%", fontsize=8.5, color="gray")
    a2.set_xlabel("UE per cell")
    a2.set_ylabel("Mean frame success rate (%)")
    a2.set_title("Fig.6  Frame success rate (60 s quick validation)")
    a2.set_ylim(97.5, 100.2)
    a2.grid(alpha=0.3)

    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=160)
    print("wrote", OUT)
    for k, v in d.items():
        print("  %-5s ue=%s sat=%s fsr=%s" % (k, v["ue"], v["sat"], v["fsr"]))


if __name__ == "__main__":
    main()