"""Summarise an ns-3 FlowMonitor XML trace.

Reads the per-flow counters and the delay histograms that rtsr-simulation.cc
writes to rtsr-flowmon.xml, then reports per-flow and per-class numbers,
including the share of packets whose delay exceeds a PDB.

    python3 analyze_trace.py rtsr-flowmon.xml --pdb-ms 10
"""

import argparse
import xml.etree.ElementTree as ET

SR_MODEL_PORT = 5000


def parse(path):
    root = ET.parse(path).getroot()

    ports = {}
    for flow in root.iter("Flow"):
        flow_id = flow.get("flowId")
        if flow_id is None or flow.get("destinationPort") is None:
            continue
        ports[int(flow_id)] = int(flow.get("destinationPort"))

    flows = []
    for node in root.iter("Flow"):
        if node.get("txPackets") is None:
            continue
        # Only the delay histogram: the same <Flow> node also carries jitter
        # (seconds) and packet-size (bytes) histograms, whose bins would
        # otherwise be mixed into the PDB accounting.
        hist = node.find("delayHistogram")
        bins = [(float(b.get("start")), float(b.get("width")), int(b.get("count")))
                for b in (hist.iter("bin") if hist is not None else [])]
        flows.append({
            "id": int(node.get("flowId")),
            "tx_packets": int(node.get("txPackets")),
            "rx_packets": int(node.get("rxPackets")),
            "lost_packets": int(node.get("lostPackets")),
            "tx_bytes": int(node.get("txBytes")),
            "rx_bytes": int(node.get("rxBytes")),
            "delay_sum_s": float(node.get("delaySum").strip("+").rstrip("ns")) * 1e-9,
            "bins": bins,
        })
    return flows, ports


def pdb_exceed(bins, pdb_s):
    total = sum(c for _, _, c in bins)
    if not total:
        return 0.0
    late = sum(c for start, width, c in bins if start + width > pdb_s)
    return late / total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xml")
    ap.add_argument("--pdb-ms", type=float, default=10.0)
    args = ap.parse_args()

    flows, ports = parse(args.xml)
    pdb_s = args.pdb_ms / 1000.0

    print(f"{'flow':>4} {'dst port':>8} {'kind':<9} {'tx':>7} {'rx':>7} {'lost':>5} "
          f"{'mean delay':>11} {'>PDB':>7} {'tx (MB)':>8}")
    print("-" * 78)

    agg = {}
    for f in flows:
        port = ports.get(f["id"], -1)
        kind = "SR model" if port == SR_MODEL_PORT else "XR video"
        mean_ms = (f["delay_sum_s"] / f["rx_packets"] * 1000) if f["rx_packets"] else 0.0
        late = pdb_exceed(f["bins"], pdb_s)
        print(f"{f['id']:>4} {port:>8} {kind:<9} {f['tx_packets']:>7} {f['rx_packets']:>7} "
              f"{f['lost_packets']:>5} {mean_ms:>10.1f}ms {late:>6.1%} {f['tx_bytes'] / 1048576:>8.2f}")
        a = agg.setdefault(kind, {"tx": 0, "rx": 0, "lost": 0, "bytes": 0, "bins": []})
        a["tx"] += f["tx_packets"]
        a["rx"] += f["rx_packets"]
        a["lost"] += f["lost_packets"]
        a["bytes"] += f["tx_bytes"]
        a["bins"].extend(f["bins"])

    print()
    print(f"=== aggregate by class (PDB = {args.pdb_ms:g} ms) ===")
    for kind, a in sorted(agg.items()):
        late = pdb_exceed(a["bins"], pdb_s)
        delivery = a["rx"] / a["tx"] if a["tx"] else 0.0
        print(f"{kind:<9} tx={a['tx']:>6} pkts  delivery={delivery:>6.1%}  "
              f"delay>PDB={late:>6.1%}  bytes={a['bytes'] / 1048576:>7.2f} MB")


if __name__ == "__main__":
    main()
