"""Merge the per-layer counters of one RTSR run into a single report.

Inputs (all produced by the same simulation run, in its working directory):
    frame_stats_port<port>_ue<i>.csv   L1 application frames (XrFrameSink)
    rlc_drops.csv                      L3 RLC SDU drops (TxDrop trace)
    rtsr-flowmon.xml                   L2 IP packets (FlowMonitor)
    mac_tb.csv                         L4 MAC scheduled TBs (DlScheduling)
    phy_tb.csv                         L5 PHY received TBs / BLER / SINR

Usage:
    python3 layer_stats.py --dir . --out layer_report.md
"""

import argparse
import csv
import glob
import os
import xml.etree.ElementTree as ET


def read_csv_rows(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["_file"] = os.path.basename(path)
                rows.append(r)
    return rows


def read_kv(path):
    """Read a two-column metric,value CSV into a dict of floats."""
    if not os.path.isfile(path):
        return None
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                out[r["metric"]] = float(r["value"])
            except (KeyError, ValueError):
                continue
    return out


def read_ip(path):
    if not os.path.isfile(path):
        return None, None
    root = ET.parse(path).getroot()
    ports = {}
    for f in root.iter("Flow"):
        if f.get("destinationPort") is not None:
            ports[int(f.get("flowId"))] = int(f.get("destinationPort"))
    video = {"tx": 0, "rx": 0}
    model = {"tx": 0, "rx": 0}
    for f in root.iter("Flow"):
        if f.get("txPackets") is None:
            continue
        bucket = model if ports.get(int(f.get("flowId"))) == 5000 else video
        bucket["tx"] += int(f.get("txPackets"))
        bucket["rx"] += int(f.get("rxPackets"))
    return video, model


def pct(x, y):
    return 100.0 * x / y if y else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=".")
    ap.add_argument("--out", default="layer_report.md")
    args = ap.parse_args()

    d = args.dir
    frames = read_csv_rows(os.path.join(d, "frame_stats_port*_ue*.csv"))
    drops = read_csv_rows(os.path.join(d, "rlc_drops.csv"))
    video_ip, model_ip = read_ip(os.path.join(d, "rtsr-flowmon.xml"))
    mac = read_kv(os.path.join(d, "mac_tb.csv"))
    phy = read_kv(os.path.join(d, "phy_tb.csv"))
    src = read_kv(os.path.join(d, "source_frames.csv"))

    # ---- L1 ----
    n_frames = len(frames)
    n_complete = sum(1 for r in frames if r["complete"] == "1")
    n_in_pdb = sum(1 for r in frames if r["within_pdb"] == "1")
    rx_pkts = sum(int(r["pkts"]) for r in frames)
    exp_pkts = sum(int(r["expected_pkts"]) for r in frames)
    frames_sent = int(src.get("frames_sent", n_frames)) if src else n_frames
    fully_dropped = max(0, frames_sent - n_frames)
    fsr = pct(n_in_pdb, frames_sent)
    frame_loss = pct(n_frames - n_complete, n_frames)

    # ---- L2 ----
    ip_tx, ip_rx = (video_ip["tx"], video_ip["rx"]) if video_ip else (0, 0)
    l2_loss = pct(ip_tx - ip_rx, ip_tx)
    ip_lost = ip_tx - ip_rx

    # ---- L3 ----
    rlc_sdu = sum(int(r["dropped_sdus"]) for r in drops) if drops else 0
    rlc_frames = len(drops) if drops else 0
    video_sdu_total = rlc_sdu + rx_pkts
    l3_rate = pct(rlc_sdu, video_sdu_total)

    # ---- L4 / L5 ----
    mac_tbs = int(mac.get("scheduled_tbs", 0)) if mac else None
    mac_bytes = int(mac.get("scheduled_bytes", 0)) if mac else None
    mac_retx = int(mac.get("retransmissions", 0)) if mac else None
    phy_tbs = int(phy.get("rx_tbs", 0)) if phy else None
    phy_corrupt = int(phy.get("corrupt_tbs", 0)) if phy else None
    bler = phy.get("bler_percent", 0.0) if phy else None
    sinr = phy.get("mean_sinr_db", 0.0) if phy else None

    L = []
    L.append("# 五层丢包汇总（单次运行）\n")
    L.append("| 层 | 指标 | 数值 | 说明 |")
    L.append("|---|---|---:|---|")
    L.append(f"| L1 应用 | 源端发帧 / 见到 / PDB 内 | {frames_sent} / {n_frames} / {n_in_pdb} | FSR **{fsr:.2f}%** |")
    L.append(f"| L1 应用 | 整帧全丢 | {fully_dropped} | sink 无记录 |")
    L.append(f"| L1 应用 | 帧丢失率 | **{frame_loss:.2f}%** | 不完整帧占比 |")
    L.append(f"| L2 IP | 视频包 tx / rx | {ip_tx} / {ip_rx} | 丢 {ip_lost}（**{l2_loss:.3f}%**） |")
    if model_ip:
        L.append(f"| L2 IP | 模型流 tx / rx | {model_ip['tx']} / {model_ip['rx']} | "
                 f"丢 {model_ip['tx'] - model_ip['rx']} |")
    L.append(f"| L3 RLC | 视频 SDU 丢弃 | {rlc_sdu} | 可归属 {rlc_frames} 帧（**{l3_rate:.3f}%**） |")
    if mac is not None:
        L.append(f"| L4 MAC | 调度 TB / 字节 | {mac_tbs} / {mac_bytes / 1048576:.2f} MB | "
                 f"重传 {mac_retx} |")
    else:
        L.append("| L4 MAC | — | 缺失 | 未生成 mac_tb.csv |")
    if phy is not None:
        L.append(f"| L5 PHY | 接收 TB / 损坏 | {phy_tbs} / {phy_corrupt} | "
                 f"BLER **{bler:.3f}%**，SINR {sinr:.1f} dB |")
    else:
        L.append("| L5 PHY | — | 缺失 | 未生成 phy_tb.csv |")

    # ---- checks ----
    checks = []

    def add(name, detail, ok):
        checks.append((name, detail, ok))

    if n_frames and drops:
        frame_loss_all = pct(frames_sent - n_complete, frames_sent)
        add("帧丢失率(含整帧丢) ≥ RLC SDU 丢弃率", f"{frame_loss_all:.2f}% vs {l3_rate:.3f}%",
            frame_loss_all >= l3_rate - 0.5)

    if ip_tx:
        add("IP 丢失率 ≤ RLC 丢弃率 + 1pp", f"{l2_loss:.3f}% vs {l3_rate:.3f}%",
            l2_loss <= l3_rate + 1.0)

    if ip_tx and rlc_sdu:
        ratio = rlc_sdu / max(1, ip_lost)
        add("RLC 丢弃 / IP 丢失 ≈ 1", f"{rlc_sdu} / {ip_lost} = {ratio:.1f}×",
            ratio <= 2.0)

    if mac_tbs and phy_tbs:
        ratio = phy_tbs / mac_tbs
        add("PHY 接收 TB ≈ MAC 调度 TB", f"{phy_tbs} / {mac_tbs} = {ratio:.2f}×",
            0.9 <= ratio <= 1.1)

    if phy is not None and mac is not None:
        add("PHY 平均 SINR 在合理区间", f"{sinr:.1f} dB", -10.0 <= sinr <= 40.0)

    if mac is not None and mac_bytes is not None and exp_pkts:
        # scheduled bytes should be >= application bytes (headers + retransmissions)
        app_bytes = sum(int(r["frame_bytes"]) for r in frames)
        add("MAC 调度字节 ≥ 应用层字节", f"{mac_bytes} vs {app_bytes}",
            mac_bytes >= app_bytes * 0.9)

    L.append("\n## 一致性校验\n")
    L.append("| 检查 | 数值 | 结果 |")
    L.append("|---|---|---|")
    for name, detail, ok in checks:
        L.append(f"| {name} | {detail} | {'✅' if ok else '❌'} |")

    L.append("\n## 备注\n")
    L.append(f"- 应用层收到包 {rx_pkts}，源端发送包 {exp_pkts}，差 {exp_pkts - rx_pkts}")
    L.append(f"- IP 层丢失 {ip_lost}，RLC 报丢 {rlc_sdu}，"
             f"两者比 {rlc_sdu / max(1, ip_lost):.1f}×")
    if phy is not None:
        L.append(f"- PHY BLER {bler:.3f}%，说明丢包主要来自队列而非空口误码"
                 if bler < 1.0 else f"- PHY BLER {bler:.3f}%，空口误码是主要丢包来源")

    text = "\n".join(L) + "\n"
    with open(os.path.join(d, args.out), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
