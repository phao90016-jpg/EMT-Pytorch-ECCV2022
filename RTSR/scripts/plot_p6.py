#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plot P6 results: Fig.5 (satisfied UE ratio) and Fig.6 (mean frame success rate).

Reads results/p6/summary2.csv.  NOTE: the csv stores the total number of UEs, so the
x axis is ues / CELLS.  Labels are in English because this image has no CJK fonts.

Usage:  emt-env/bin/python RTSR/scripts/plot_p6.py
"""
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)                      # .../RTSR
CSV = os.path.join(REPO, "results", "p6", "summary2.csv")
OUT = os.path.join(REPO, "docs", "figs", "p6_fig5_fig6.png")
CELLS = 21                                        # 7 sites x 3 sectors


def load():
    data = {"conventional": {"ue": [], "sat": [], "fsr": []},
            "rtsr": {"ue": [], "sat": [], "fsr": []}}
    with open(CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            run = row["run"].strip()
            scheme = {"conv": "conventional", "conventional": "conventional",
                      "rtsr": "rtsr"}.get(run.rsplit("-", 1)[-1])
            if scheme is None:
                continue                          # skip g0 / probe rows
            try:
                ue_per_cell = int(row["ues"]) / CELLS
            except (KeyError, ValueError):
                continue
            data[scheme]["ue"].append(ue_per_cell)
            data[scheme]["sat"].append(float(row["satisfied_pct"]))
            data[scheme]["fsr"].append(float(row["mean_fsr_paper"]))
    for v in data.values():
        order = sorted(range(len(v["ue"])), key=lambda i: v["ue"][i])
        for key in ("ue", "sat", "fsr"):
            v[key] = [v[key][i] for i in order]
    return data


def main():
    if not os.path.isfile(CSV):
        sys.exit("missing %s" % CSV)
    d = load()
    if not d["conventional"]["ue"] and not d["rtsr"]["ue"]:
        sys.exit("no data rows in %s" % CSV)

    style = {
        "conventional": dict(color="#c0392b", marker="o", lw=2, ms=9,
                             label="Conventional 20 Mbps"),
        "rtsr": dict(color="#2471a3", marker="s", lw=2, ms=9,
                     label="RTSR 10 Mbps + model"),
    }

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))

    # ---------------- Fig.5 ----------------
    for scheme in ("conventional", "rtsr"):
        v = d[scheme]
        if not v["ue"]:
            continue
        ax1.plot(v["ue"], v["sat"], **style[scheme])
        for i, (x, y) in enumerate(zip(v["ue"], v["sat"])):
            off = (0, 11) if scheme == "rtsr" else (0, -19)
            if scheme == "conventional":
                if i == 0:
                    off = (17, -4)      # first point sits on the 90% line
                elif y < 6:
                    off = (0, 13)       # low points would be clipped below the axis
            ax1.annotate("%.1f" % y, (x, y), textcoords="offset points",
                         xytext=off, ha="center", fontsize=8.5,
                         color=style[scheme]["color"])

    ax1.axvspan(4, 17, color="#eef2f4", zorder=0)
    ax1.text(10.6, 55, "paper: both > 90%\nbelow 17 UE/cell", fontsize=8.5,
             color="#566573", ha="center")
    ax1.axhline(90, color="gray", ls="--", lw=1)
    ax1.text(19.6, 91.5, "90% criterion", fontsize=8, color="gray", ha="right")
    ax1.set_xlabel("UE per cell")
    ax1.set_ylabel("Satisfied UEs (%)  [per-UE FSR > 99.5%]")
    ax1.set_title("Fig.5  Satisfied UE ratio")
    ax1.set_xlim(4, 20)
    ax1.set_ylim(-5, 112)
    ax1.grid(alpha=0.3)

    # ---------------- Fig.6 ----------------
    for scheme in ("conventional", "rtsr"):
        v = d[scheme]
        if not v["ue"]:
            continue
        ax2.plot(v["ue"], v["fsr"], **style[scheme])
        for i, (x, y) in enumerate(zip(v["ue"], v["fsr"])):
            off = (0, 11) if scheme == "rtsr" else (0, -18)
            if i == 0:                  # both schemes have a point at 6 UE/cell
                off = (15, 7) if scheme == "rtsr" else (-16, -7)
            ax2.annotate("%.1f" % y, (x, y), textcoords="offset points",
                         xytext=off, ha="center", fontsize=8.5,
                         color=style[scheme]["color"])

    ax2.axhline(99.5, color="gray", ls="--", lw=1)
    ax2.text(4.25, 94.6, "per-UE threshold 99.5%", fontsize=8, color="gray", ha="left")
    ax2.set_xlabel("UE per cell")
    ax2.set_ylabel("Mean frame success rate (%)")
    ax2.set_title("Fig.6  Frame success rate")
    ax2.set_xlim(4, 20)
    ax2.set_ylim(45, 104)
    ax2.grid(alpha=0.3)

    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=160)
    print("wrote", OUT)
    for scheme, v in d.items():
        print("  %-13s UE/cell=%s sat=%s fsr=%s" %
              (scheme, [round(x, 2) for x in v["ue"]], v["sat"], v["fsr"]))


if __name__ == "__main__":
    main()
