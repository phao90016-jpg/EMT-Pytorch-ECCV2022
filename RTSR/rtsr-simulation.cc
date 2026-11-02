// Copyright (c) 2023 Centre Tecnologic de Telecomunicacions de Catalunya (CTTC)
//
// SPDX-License-Identifier: GPL-2.0-only

#include "ns3/antenna-module.h"
#include "ns3/applications-module.h"
#include "ns3/boolean.h"
#include "ns3/config-store-module.h"
#include "ns3/config-store.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-apps-module.h"
#include "ns3/internet-module.h"
#include "ns3/lte-enb-rrc.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/nr-module.h"
#include "ns3/nr-mac-scheduler-lc-qos.h"
#include "ns3/packet-sink.h"
#include "ns3/point-to-point-module.h"
#include "ns3/random-variable-stream.h"
#include "ns3/xr-traffic-mixer-helper.h"
#include "rtsr-frame-agents.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <map>
#include <set>
#include <utility>
#include <vector>

/**
 * \file cttc-nr-traffic-3gpp-xr.cc
 * \ingroup examples
 * \brief Simple topology consisting of 1 GNB and various UEs.
 *  Can be configured with different 3GPP XR traffic generators (by using
 *  XR traffic mixer helper).
 *
 * To run the simulation with the default configuration one shall run the
 * following in the command line:
 *
 * ./ns3 run cttc-nr-traffic-generator-3gpp-xr
 *
 */

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("CttcNrTraffic3gppXr");

// ---- paper traffic model mode (P0: frame-level instrumentation) ----
static bool g_paperTraffic = false;
static double g_fps = 60.0;
static double g_videoBitrateMbps = 10.0;
static double g_frameStdRatio = 0.105;
static double g_frameMinRatio = 0.5;
static double g_frameMaxRatio = 1.5;
static double g_jitterStdMs = 2.0;
static double g_jitterLimitMs = 4.0;
static double g_framePdbMs = 10.0;
static uint32_t g_mtu = 1400;
static uint32_t g_appStartMs = 400;
static uint32_t g_appDurationMs = 60000;
// frame sinks must stop *before* Simulator::Stop, otherwise their stop
// event never runs and the CSV/summary is lost
static ApplicationContainer g_frameSinks;
static NetDeviceContainer g_ueDevicesForPhy;
static NetDeviceContainer g_gnbDevices;
// ---- P4.1b: 3-sector sites ----
// One site hosts g_numSectors co-located gNBs whose antenna bearing angles are
// spread evenly over 360 deg.  g_gnbDevSiteSector is indexed site-major, i.e.
// g_gnbDevSiteSector[site * g_numSectors + sector] is the gNB of that sector.
static bool g_sectorized = false;
static uint32_t g_numSectors = 3;
static std::vector<Vector> g_sitePos;
static std::vector<Ptr<NetDevice>> g_gnbDevSiteSector;
// The 3GPP channel model asserts that two devices never share one position, so the
// sectors of a site are mounted a metre apart (0.5 % of the 200 m ISD, i.e. the
// path loss / angles towards the UEs stay unchanged).  g_sitePos keeps the true
// site centre and is what UE-to-sector assignment uses.
static const double g_sectorOffsetM = 1.0;
// ---- P4.2: multi-ring lattice and centre-only statistics ----
// g_siteRings >= 0 switches to a hexagonal lattice with that many site rings
// (R=1 -> 7 sites, R=2 -> 19, R=3 -> 37); -1 keeps the legacy --numSites layout.
static int32_t g_siteRings = -1;
// g_statsRings >= 0 restricts every layer's statistics to the sites whose ring
// index is <= g_statsRings (the outer rings then only contribute interference).
static int32_t g_statsRings = -1;
// g_uePerCell > 0 drops that many UEs around every site (per sector) instead of
// one disc of UEs around the centre.
static uint32_t g_uePerCell = 0;
static std::vector<uint32_t> g_siteRing;              // ring index per site
static std::set<uint32_t> g_centerGnbNodeIds;         // gNB node ids that are measured
static std::set<uint16_t> g_centerCellIds;            // their cell ids
static std::map<uint32_t, uint32_t> g_ueServingSite;  // UE node id -> site index
static uint32_t g_centerUeCount = 0;
static uint32_t g_outerUeCount = 0;
// ---- P5.1: indoor / outdoor split ----
static uint32_t g_indoorUeCount = 0;
static std::set<uint32_t> g_indoorUeNodes; // node ids of the indoor UEs
// ---- P5.2: UE mobility ----
static std::vector<Vector> g_ueStartPos; // initial UE positions, for the speed check
static std::vector<std::pair<double, double>> g_sinrTrace; // (time_ms, sinr_db)
static uint16_t g_refCellId = UINT16_MAX;
static uint16_t g_refRnti = UINT16_MAX;
static uint32_t g_sinrTraceCap = 20000;
// ---- P6: checkpointing ----
// ns-3 has no way to save/restore a running simulation, so a long run that dies is
// lost.  Flushing every statistic periodically at least leaves the data up to the last
// checkpoint on disk; checkpoint.txt says how far the run got and whether it finished.
static uint32_t g_checkpointMs = 0;
static uint32_t g_checkpointsWritten = 0;
// P6: warm-up - the frame sinks (and therefore the FSR denominators) start this much
// after the traffic sources, so the cell-search / RRC phase is not counted.
static uint32_t g_warmupMs = 0;
// P6: progress heartbeat.  A long run used to be a black box - no output between the
// start and the end, so a run that took 3 hours could not be told apart from a stuck
// one.  This writes one small file periodically (NOT the CSVs: flushing 546 per-UE
// files every second would itself cost minutes).
static uint32_t g_progressMs = 0;
static std::chrono::steady_clock::time_point g_wallStart;
// P6: pure diagnostics that cost time but never feed a result.
static bool g_enablePing = true;
static bool g_flowmonProbes = false;
static std::set<uint32_t> g_centerUeIps; // Ipv4Address.Get() of the measured UEs
static bool IsCenterSite(uint32_t site);
static bool IsCenterUe(uint32_t ueNodeId);
static std::string g_tddPattern;
static uint32_t g_pdcchSymbols = 0;
// conventional = 20 Mbps pure video, no SR model flow (Fig.5 baseline)
static bool g_conventional = false;

// ---- P0.3: RLC SDU drop accounting (TxDrop trace on the gNB RLC) ----
static uint64_t g_rlcDrops = 0;
static uint64_t g_rlcDropsOutside = 0; // rejected by the P4.2 centre-cell filter
static uint64_t g_rlcUnparsed = 0;     // context had no /NodeList/<id>/ (counted anyway)
static uint64_t g_rlcAttributed = 0;
static std::set<uint64_t> g_rlcDistinct;
static uint64_t g_rlcDroppedBytes = 0;
static std::map<uint32_t, uint64_t> g_rlcDropsPerFrame;

static void
RlcDropCallback(std::string context, Ptr<const Packet> p)
{
    // When the statistics are restricted, only drops of the measured cells count.
    // The context looks like "/NodeList/<gnbNodeId>/DeviceList/...", so the node id
    // of the gNB that owns this RLC entity is all we need.
    if (g_statsRings >= 0)
    {
        const std::string head = "/NodeList/";
        const size_t pos = context.find(head);
        if (pos == std::string::npos)
        {
            // No node id in the context: cannot filter, count it and say so.
            ++g_rlcUnparsed;
        }
        else
        {
            const size_t begin = pos + head.size();
            const size_t end = context.find('/', begin);
            const std::string idStr = context.substr(begin, end - begin);
            const uint32_t nodeId = static_cast<uint32_t>(std::strtoul(idStr.c_str(), nullptr, 10));
            if (g_centerGnbNodeIds.find(nodeId) == g_centerGnbNodeIds.end())
            {
                ++g_rlcDropsOutside;
                return;
            }
        }
    }
    ++g_rlcDrops;
    g_rlcDroppedBytes += p->GetSize();
    // The RLC SDU starts with the PDCP/IP headers, so scan the first bytes for the
    // application frame magic instead of assuming a fixed offset.
    const uint32_t scanLen = std::min<uint32_t>(p->GetSize(), 96);
    if (scanLen >= FrameHeader::kSize)
    {
        uint8_t buf[96];
        p->CopyData(buf, scanLen);
        for (uint32_t off = 0; off + FrameHeader::kSize <= scanLen; ++off)
        {
            if (buf[off] == 0xC3 && buf[off + 1] == 0xA5) // little-endian 0xA5C3
            {
                uint8_t hdrBuf[FrameHeader::kSize];
                std::memcpy(hdrBuf, buf + off, FrameHeader::kSize);
                FrameHeader hdr;
                if (hdr.ReadFrom(hdrBuf))
                {
                    ++g_rlcAttributed;
                    // the same SDU can be reported more than once; keep unique keys
                    g_rlcDistinct.insert((static_cast<uint64_t>(hdr.frameId) << 32) | hdr.seq);
                    ++g_rlcDropsPerFrame[hdr.frameId];
                }
                break;
            }
        }
    }
}

// Connect the gNB RLC TxDrop trace once the DRB exists; retry until it does.
// Convert "DDDSU" into the PHY's attribute format "DL|DL|DL|S|UL".
static std::string
ConvertTddPattern(const std::string& in)
{
    if (in.find('|') != std::string::npos)
    {
        return in;
    }
    std::string conv;
    for (char c : in)
    {
        std::string tok = (c == 'D') ? "DL" : (c == 'U') ? "UL" : (c == 'S') ? "S" : "F";
        conv += (conv.empty() ? "" : "|") + tok;
    }
    return conv;
}

// Read back the pattern of every gNB PHY (verification only - setting it must happen
// through the helper attribute before the PHY is created).
static void
ApplyTddPattern()
{
    std::string pattern = g_tddPattern;
    if (pattern.empty())
    {
        return;
    }
    if (pattern.find('|') == std::string::npos)
    {
        std::string conv;
        for (char c : pattern)
        {
            std::string tok = (c == 'D') ? "DL" : (c == 'U') ? "UL" : (c == 'S') ? "S" : "F";
            conv += (conv.empty() ? "" : "|") + tok;
        }
        pattern = conv;
    }
    uint32_t applied = 0;
    for (uint32_t i = 0; i < g_gnbDevices.GetN(); ++i)
    {
        Ptr<NrGnbNetDevice> gnb = DynamicCast<NrGnbNetDevice>(g_gnbDevices.Get(i));
        if (!gnb)
        {
            continue;
        }
        Ptr<NrGnbPhy> phy = gnb->GetPhy(0);
        if (!phy)
        {
            continue;
        }
        if (i == 0)
        {
            std::cout << "[TDD] requested " << g_tddPattern << " -> " << pattern
                      << ", PHY reports " << phy->GetPattern() << " (slot period "
                      << phy->GetSlotPeriod() << ")" << std::endl;
        }
        ++applied;
    }
    std::cout << "[TDD] applied to " << applied << " gNB PHY(s)" << std::endl;
}

static void
TryConnectRlc()
{
    static uint32_t attempts = 0;
    bool ok = Config::ConnectFailSafe(
        "/NodeList/*/DeviceList/*/LteEnbRrc/UeMap/*/DataRadioBearerMap/*/LteRlc/TxDrop",
        MakeCallback(&RlcDropCallback));
    if (ok)
    {
        std::cout << "[RLC] TxDrop trace connected after " << (attempts + 1) << " attempt(s)"
                  << std::endl;
        return;
    }
    if (++attempts < 40)
    {
        Simulator::Schedule(MilliSeconds(100), &TryConnectRlc);
    }
    else
    {
        std::cout << "[RLC] WARNING: could not connect TxDrop trace" << std::endl;
    }
}

// ---- P0.4 / P0.5: MAC TB scheduling and PHY TB reception ----
static uint64_t g_macTbs = 0;
static uint64_t g_macAllEvents = 0;  // every DlScheduling callback, before filtering
static uint64_t g_macTbSizeZero = 0; // dropped: tbSize == 0
static uint64_t g_macStreamGt0 = 0;  // dropped: streamId > 0
static uint64_t g_macRetx = 0;
static uint64_t g_macTbBytes = 0;
static uint64_t g_phyTbs = 0;
static uint64_t g_phyCorrupt = 0;
static uint64_t g_phyBytes = 0;
static double g_sinrSum = 0.0;
static uint32_t g_sinrCount = 0;
// RxPacketTraceUe is emitted once per MAC PDU in the received burst, not once per
// TB, so the same TB would be counted several times (1.3x at high load).  One UE
// receives at most one TB per slot, hence the (frame, slot, rnti) key.
static std::set<uint64_t> g_phyTbKeys;

// Per-UE PHY statistics: the network-wide mean hides whether the interference is
// actually felt by some UEs, so keep a per-RNTI breakdown as well.
struct UePhyStat
{
    uint64_t tb = 0;
    uint64_t corrupt = 0;
    double sinrSum = 0.0;
    uint32_t sinrCount = 0;
};
// RNTIs are handed out per cell starting from 1, so the map key is
// (cellId << 16) | rnti - a bare RNTI would merge UEs of different cells.
static std::map<uint64_t, UePhyStat> g_uePhyStats;
// Wideband DL-control SINR: fired once per PDCCH reception with the SINR averaged over
// every RB that carried control, so it does not depend on a TB's RB allocation.  This
// is the metric used to resolve the mobility effect (per-TB SINR cannot: a stationary
// UE already shows a ~36 dB spread purely from which RBs each TB got).
static double g_ctrlSinrSum = 0.0;
static uint64_t g_ctrlSinrCount = 0;
static std::map<int, std::pair<double, uint64_t>> g_ctrlSinrBuckets; // 1 s buckets
// Wideband DL *data* SINR: fired with the SINR averaged over every RB of the band, so
// unlike the per-TB value it does not depend on which RBs the TB was given.
static double g_wbSinrSum = 0.0;
static uint64_t g_wbSinrCount = 0;
static std::map<int, std::pair<double, uint64_t>> g_wbSinrBuckets; // 1 s buckets
// Same idea on the MAC side: one UE gets at most one DL TB per slot, so
// (cell, frame, slot, rnti) identifies a TB and reveals duplicated DCI traces.
static std::set<uint64_t> g_macTbKeys;
static uint64_t g_macDuplicateEvents = 0;

static void
OnDlScheduling(uint16_t cellId, NrSchedulingCallbackInfo info)
{
    ++g_macAllEvents;
    if (!info.m_tbSize)
    {
        ++g_macTbSizeZero;
    }
    if (info.m_streamId > 0)
    {
        ++g_macStreamGt0;
    }
    if (info.m_tbSize && info.m_streamId <= 0)
    {
        const uint64_t tbKey = (static_cast<uint64_t>(cellId) << 48) |
                               (static_cast<uint64_t>(info.m_frameNum & 0xffff) << 32) |
                               (static_cast<uint64_t>(info.m_slotNum & 0xff) << 24) |
                               (static_cast<uint64_t>(info.m_symStart) << 16) | info.m_rnti;
        if (!g_macTbKeys.insert(tbKey).second)
        {
            ++g_macDuplicateEvents;
            return;
        }
        ++g_macTbs;
        g_macTbBytes += info.m_tbSize;
        // count retransmissions separately through the RV field
        if (info.m_rv != 0)
        {
            ++g_macRetx;
        }
    }
}

static void
OnDlCtrlSinr(uint16_t cellId, uint16_t rnti, double sinrLinear, uint16_t bwpId, uint8_t streamId)
{
    if (streamId > 0 || sinrLinear <= 0.0)
    {
        return;
    }
    // No cell filter here: the trace is connected only to the measured UEs, and
    // NrUePhy::GetCellId() does not necessarily equal the serving cell id for a UE PHY
    // (filtering on it silently dropped every sample).
    if (g_refCellId == UINT16_MAX)
    {
        g_refCellId = cellId;
        g_refRnti = rnti;
        std::cout << "[P5.3] first DL-ctrl SINR event: cellId=" << cellId << " rnti=" << rnti
                  << " sinr=" << (10.0 * std::log10(sinrLinear)) << " dB" << std::endl;
    }
    const double sinrDb = 10.0 * std::log10(sinrLinear);
    g_ctrlSinrSum += sinrDb;
    ++g_ctrlSinrCount;
    if (cellId == g_refCellId && rnti == g_refRnti)
    {
        auto& bucket =
            g_ctrlSinrBuckets[static_cast<int>(Simulator::Now().GetMilliSeconds() / 1000.0)];
        bucket.first += sinrDb;
        ++bucket.second;
    }
}

static void
OnDlDataSinr(uint16_t cellId, uint16_t rnti, double sinrLinear, uint16_t bwpId, uint8_t streamId)
{
    if (streamId > 0 || sinrLinear <= 0.0)
    {
        return;
    }
    if (g_refCellId == UINT16_MAX)
    {
        g_refCellId = cellId;
        g_refRnti = rnti;
    }
    const double sinrDb = 10.0 * std::log10(sinrLinear);
    g_wbSinrSum += sinrDb;
    ++g_wbSinrCount;
    if (cellId == g_refCellId && rnti == g_refRnti)
    {
        auto& bucket =
            g_wbSinrBuckets[static_cast<int>(Simulator::Now().GetMilliSeconds() / 1000.0)];
        bucket.first += sinrDb;
        ++bucket.second;
    }
}

static void
OnRxPacketTraceUe(RxPacketTraceParams params)
{
    // (cell, frame, slot, symbol, rnti): one TB per allocation, and a UE may get
    // more than one allocation in the same slot.
    const uint64_t tbKey = (static_cast<uint64_t>(params.m_cellId) << 48) |
                           (static_cast<uint64_t>(params.m_frameNum & 0xffff) << 32) |
                           (static_cast<uint64_t>(params.m_slotNum & 0xff) << 24) |
                           (static_cast<uint64_t>(params.m_symStart) << 16) | params.m_rnti;
    if (g_statsRings >= 0 &&
        g_centerCellIds.find(static_cast<uint16_t>(params.m_cellId)) == g_centerCellIds.end())
    {
        return; // reception of a cell outside the measured scope
    }
    if (!g_phyTbKeys.insert(tbKey).second)
    {
        return; // already counted this TB (one of its other MAC PDUs)
    }
    ++g_phyTbs;
    g_phyBytes += params.m_tbSize;
    if (params.m_corrupt)
    {
        ++g_phyCorrupt;
    }
    // m_sinr is reported in linear scale; convert to dB for the report.
    if (params.m_sinr > 0.0)
    {
        g_sinrSum += 10.0 * std::log10(params.m_sinr);
        ++g_sinrCount;
    }

    if (g_refCellId == UINT16_MAX)
    {
        // Pin the time series to the first measured UE that actually receives data.
        g_refCellId = static_cast<uint16_t>(params.m_cellId);
        g_refRnti = params.m_rnti;
    }
    if (params.m_cellId == g_refCellId && params.m_rnti == g_refRnti &&
        g_sinrTrace.size() < g_sinrTraceCap && params.m_sinr > 0.0)
    {
        g_sinrTrace.emplace_back(Simulator::Now().GetMilliSeconds(),
                                 10.0 * std::log10(params.m_sinr));
    }

    UePhyStat& ueStat = g_uePhyStats[(params.m_cellId << 16) | params.m_rnti];
    ++ueStat.tb;
    if (params.m_corrupt)
    {
        ++ueStat.corrupt;
    }
    if (params.m_sinr > 0.0)
    {
        ueStat.sinrSum += 10.0 * std::log10(params.m_sinr);
        ++ueStat.sinrCount;
    }
}

static void
DumpMacPhy(bool announce)
{
    std::ofstream mac("mac_tb.csv");
    mac << "metric,value\n";
    mac << "scheduled_tbs," << g_macTbs << "\n";
    mac << "scheduled_bytes," << g_macTbBytes << "\n";
    mac << "retransmissions," << g_macRetx << "\n";
    mac << "measured_cells," << g_centerCellIds.size() << "\n";

    std::ofstream phy("phy_tb.csv");
    phy << "metric,value\n";
    phy << "rx_tbs," << g_phyTbs << "\n";
    phy << "corrupt_tbs," << g_phyCorrupt << "\n";
    phy << "rx_bytes," << g_phyBytes << "\n";
    phy << "measured_cells," << g_centerCellIds.size() << "\n";
    phy << "measured_ues," << g_centerUeCount << "\n";
    double bler = g_phyTbs ? 100.0 * g_phyCorrupt / g_phyTbs : 0.0;
    double meanSinr = g_sinrCount ? g_sinrSum / g_sinrCount : 0.0;
    phy << "bler_percent," << bler << "\n";
    phy << "mean_sinr_db," << meanSinr << "\n";

    mac << "all_dlscheduling_events," << g_macAllEvents << "\n";
    mac << "dropped_tbsize_zero," << g_macTbSizeZero << "\n";
    mac << "dropped_stream_gt0," << g_macStreamGt0 << "\n";
    mac << "duplicate_dci_events," << g_macDuplicateEvents << "\n";
    if (!announce)
    {
        return;
    }
    std::cout << "[MAC] scheduled TBs=" << g_macTbs << " bytes=" << g_macTbBytes
              << " retx=" << g_macRetx << " | all_events=" << g_macAllEvents
              << " dropped_tbsize0=" << g_macTbSizeZero
              << " dropped_stream>0=" << g_macStreamGt0
              << " duplicate_dci=" << g_macDuplicateEvents << std::endl;
    const double ctrlSinr = g_ctrlSinrCount ? g_ctrlSinrSum / g_ctrlSinrCount : 0.0;
    phy << "wideband_ctrl_sinr_db," << ctrlSinr << "\n";
    phy << "wideband_ctrl_sinr_samples," << g_ctrlSinrCount << "\n";
    const double wbSinr = g_wbSinrCount ? g_wbSinrSum / g_wbSinrCount : 0.0;
    phy << "wideband_data_sinr_db," << wbSinr << "\n";
    phy << "wideband_data_sinr_samples," << g_wbSinrCount << "\n";
    std::cout << "[PHY] rx TBs=" << g_phyTbs << " corrupt=" << g_phyCorrupt << " BLER=" << bler
              << "% meanSINR=" << meanSinr << " dB | wideband DL-ctrl SINR=" << ctrlSinr
              << " dB (" << g_ctrlSinrCount << " samples) | wideband DL-data SINR=" << wbSinr
              << " dB (" << g_wbSinrCount << " samples)" << std::endl;

    // Per-UE breakdown: SINR spread shows whether the scenario is interference
    // limited (wide spread, low tail) or merely noise limited (all UEs high).
    for (const auto& it : g_uePhyStats)
    {
        const UePhyStat& s = it.second;
        const uint16_t cellId = it.first >> 16;
        const uint16_t rnti = it.first & 0xffff;
        const double ueSinr = s.sinrCount ? s.sinrSum / s.sinrCount : 0.0;
        const double ueBler = s.tb ? 100.0 * (double)s.corrupt / s.tb : 0.0;
        phy << "cell" << cellId << "_rnti" << rnti << "_rx_tbs," << s.tb << "\n";
        phy << "cell" << cellId << "_rnti" << rnti << "_bler_percent," << ueBler << "\n";
        phy << "cell" << cellId << "_rnti" << rnti << "_sinr_db," << ueSinr << "\n";
        std::cout << "[PHY-UE] cell=" << cellId << " rnti=" << rnti << " TBs=" << s.tb
                  << " BLER=" << ueBler << "% SINR=" << ueSinr << " dB" << std::endl;
    }
}

// Try the MAC and PHY traces once the objects exist; retry a few times.
// DlScheduling has no cell id in its payload, so the trace is connected per gNB
// device and the cell id is bound into the callback.  That is what makes the MAC
// statistics restrictable to the centre cells.
static void
OnDlSchedulingCell(uint16_t cellId, NrSchedulingCallbackInfo info)
{
    if (g_statsRings >= 0 && g_centerCellIds.find(cellId) == g_centerCellIds.end())
    {
        return;
    }
    OnDlScheduling(cellId, info);
}

static void
TryConnectMacPhy()
{
    static uint32_t attempts = 0;
    static bool phyConnectedOnce = false;
    uint32_t macConnected = 0;
    for (const auto& nd : g_gnbDevSiteSector)
    {
        Ptr<NrGnbNetDevice> gnb = DynamicCast<NrGnbNetDevice>(nd);
        if (!gnb || !gnb->GetMac(0))
        {
            continue;
        }
        const uint16_t cellId = gnb->GetCellId();
        if (g_statsRings >= 0 && g_centerCellIds.find(cellId) == g_centerCellIds.end())
        {
            continue;
        }
        if (gnb->GetMac(0)->TraceConnectWithoutContext(
                "DlScheduling",
                MakeBoundCallback(&OnDlSchedulingCell, cellId)))
        {
            ++macConnected;
        }
    }
    const bool mac = (macConnected > 0);
    if (mac && attempts == 0)
    {
        std::cout << "[MAC] DlScheduling connected on " << macConnected << " cell(s)" << std::endl;
    }
    // The UE spectrum PHY is not reachable through Config paths, so connect it
    // directly: NrUeNetDevice -> NrUePhy -> NrSpectrumPhy -> trace.
    // Connect only once: every extra Connect would add another callback and double
    // count the TBs.
    bool phy = phyConnectedOnce;
    uint32_t connected = 0;
    for (uint32_t i = 0; !phyConnectedOnce && i < g_ueDevicesForPhy.GetN(); ++i)
    {
        Ptr<NrUeNetDevice> ueDev = DynamicCast<NrUeNetDevice>(g_ueDevicesForPhy.Get(i));
        if (!ueDev)
        {
            continue;
        }
        // GetPhy()/GetSpectrumPhy() assert on an out-of-range index instead of
        // returning null, so only the configured single BWP / single stream is used.
        Ptr<NrUePhy> uePhy = ueDev->GetPhy(0);
        if (!uePhy)
        {
            continue;
        }
        Ptr<NrSpectrumPhy> specPhy = uePhy->GetSpectrumPhy(0);
        bool ok = false;
        if (specPhy &&
            specPhy->TraceConnectWithoutContext("RxPacketTraceUe",
                                                MakeCallback(&OnRxPacketTraceUe)))
        {
            ok = true;
        }
        if (uePhy->TraceConnectWithoutContext("DlCtrlSinr", MakeCallback(&OnDlCtrlSinr)))
        {
            ok = true;
        }
        if (uePhy->TraceConnectWithoutContext("DlDataSinr", MakeCallback(&OnDlDataSinr)))
        {
            ok = true;
        }
        if (ok)
        {
            ++connected;
        }
    }
    if (!phyConnectedOnce)
    {
        phy = (connected > 0);
        phyConnectedOnce = phy;
        if (phy)
        {
            std::cout << "[PHY] connected " << connected << " RxPacketTraceUe source(s)"
                      << std::endl;
        }
    }
    if (mac && phy)
    {
        std::cout << "[MAC/PHY] traces connected after " << (attempts + 1) << " attempt(s)"
                  << std::endl;
        return;
    }
    if (++attempts < 40)
    {
        Simulator::Schedule(MilliSeconds(100), &TryConnectMacPhy);
    }
    else
    {
        std::cout << "[MAC/PHY] WARNING: mac=" << mac << " phy=" << phy << std::endl;
    }
}

// The frame sinks can only count frames of which something arrived.  The measured
// total is what the sources had sent when the sinks stopped, written here so that
// layer_stats.py can use it as the FSR denominator.
static void DumpMacPhy(bool announce);
static void DumpRlcDrops(bool announce);
static void DumpSourceFrames(bool announce);

// Heartbeat: simulated time, wall time, achieved rate and ETA.  ~1 file write of a few
// hundred bytes, so it can run on a short period (e.g. every 1 s of simulated time).
static void
ProgressTick()
{
    const double simMs = Simulator::Now().GetMilliSeconds();
    const double wallS =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - g_wallStart).count();
    const double rate = (simMs > 0.0) ? (wallS * 1000.0 / simMs) : 0.0;
    const double etaS = (simMs > 0.0) ? (wallS * (g_appDurationMs - simMs) / simMs) : 0.0;
    std::ofstream st("progress.txt");
    st << "simulated_ms," << simMs << "\n";
    st << "planned_ms," << g_appDurationMs << "\n";
    st << "wall_s," << wallS << "\n";
    st << "wall_per_sim_s," << rate << "\n";
    st << "eta_s," << etaS << "\n";
    if (g_progressMs > 0 && Simulator::Now() < MilliSeconds(g_appDurationMs))
    {
        Simulator::Schedule(MilliSeconds(g_progressMs), &ProgressTick);
    }
}

static void
WriteCheckpointMarker(bool complete)
{
    std::ofstream st("checkpoint.txt");
    st << "simulated_ms," << Simulator::Now().GetMilliSeconds() << "\n";
    st << "planned_ms," << g_appDurationMs << "\n";
    st << "checkpoints," << g_checkpointsWritten << "\n";
    st << "complete," << (complete ? 1 : 0) << "\n";
}

static void
Checkpoint()
{
    ++g_checkpointsWritten;
    for (uint32_t i = 0; i < g_frameSinks.GetN(); ++i)
    {
        Ptr<XrFrameSink> sink = DynamicCast<XrFrameSink>(g_frameSinks.Get(i));
        if (sink)
        {
            sink->FlushCsv();
        }
    }
    DumpMacPhy(false);
    DumpRlcDrops(false);
    DumpSourceFrames(false);
    WriteCheckpointMarker(false);
    if (g_checkpointMs > 0 && Simulator::Now() < MilliSeconds(g_appDurationMs))
    {
        Simulator::Schedule(MilliSeconds(g_checkpointMs), &Checkpoint);
    }
}

static void
DumpSourceFrames(bool announce)
{
    uint64_t sent = 0;
    uint64_t seen = 0;
    uint64_t complete = 0;
    uint64_t inPdb = 0;
    for (const auto& t : g_frameSinkTotals)
    {
        sent += t.sentAtStop;
        seen += t.seen;
        complete += t.complete;
        inPdb += t.withinPdb;
    }
    std::ofstream out("source_frames.csv");
    out << "metric,value\n";
    out << "frames_sent," << sent << "\n";
    out << "frames_seen_by_sink," << seen << "\n";
    out << "frames_complete," << complete << "\n";
    out << "frames_within_pdb," << inPdb << "\n";
    out << "frames_never_seen," << (sent > seen ? sent - seen : 0) << "\n";
    const double fsr = sent ? (100.0 * inPdb / sent) : 0.0;
    if (!announce)
    {
        return;
    }
    std::cout << "[FRAMES] sent(by source)=" << sent << " seen(by sink)=" << seen
              << " never_seen=" << (sent > seen ? sent - seen : 0) << " complete=" << complete
              << " within_pdb=" << inPdb << " FSR=" << fsr << "%" << std::endl;
}

static void
DumpRlcDrops(bool announce)
{
    std::ofstream out("rlc_drops.csv");
    out << "frame_id,dropped_sdus\n";
    for (const auto& kv : g_rlcDropsPerFrame)
    {
        out << kv.first << "," << kv.second << "\n";
    }
    std::ofstream scope("rlc_scope.csv");
    scope << "metric,value\n";
    scope << "kept_dropped_sdus," << g_rlcDrops << "\n";
    scope << "outside_scope_dropped_sdus," << g_rlcDropsOutside << "\n";
    scope << "unparsed_events," << g_rlcUnparsed << "\n";
    if (!announce)
    {
        return;
    }
    std::cout << "[RLC] events=" << g_rlcDrops << " attributed=" << g_rlcAttributed
              << " distinct_pkts=" << g_rlcDistinct.size()
              << " frames_touched=" << g_rlcDropsPerFrame.size()
              << " outside_scope=" << g_rlcDropsOutside << " unparsed=" << g_rlcUnparsed
              << std::endl;
}



void
WriteBytesSent(Ptr<TrafficGenerator> trafficGenerator,
               uint64_t* previousBytesSent,
               uint64_t* previousWindowBytesSent,
               enum NrXrConfig NrXrConfig,
               std::ofstream* outFileTx)
{
    uint64_t totalBytesSent = trafficGenerator->GetTotalBytes();
    (*outFileTx) << "\n"
                 << Simulator::Now().GetMilliSeconds() << "\t" << *previousWindowBytesSent
                 << std::endl;
    (*outFileTx) << "\n"
                 << Simulator::Now().GetMilliSeconds() << "\t"
                 << totalBytesSent - *previousBytesSent << std::endl;

    *previousWindowBytesSent = totalBytesSent - *previousBytesSent;
    *previousBytesSent = totalBytesSent;
};

void
WriteBytesReceived(Ptr<PacketSink> packetSink, uint64_t* previousBytesReceived)
{
    uint64_t totalBytesReceived = packetSink->GetTotalRx();
    *previousBytesReceived = totalBytesReceived;
};

// Send one SR model as a burst of UDP packets.
void
SendSrModel(Ptr<Node> sourceNode, Ipv4Address destIp, uint16_t port, Time startTime)
{
    // UdpClient limits a datagram to 65507 bytes; 530 x 1024 bytes is 530 KiB.
    UdpClientHelper client(destIp, port);
    client.SetAttribute("MaxPackets", UintegerValue(530));
    client.SetAttribute("Interval", TimeValue(MicroSeconds(1)));
    client.SetAttribute("PacketSize", UintegerValue(1024));

    ApplicationContainer app = client.Install(sourceNode);
    app.Start(startTime);
    app.Stop(startTime + MilliSeconds(1));
}

void
ConfigureXrApp(NodeContainer& ueContainer,
               uint32_t i,
               Ipv4InterfaceContainer& ueIpIface,
               enum NrXrConfig config,
               uint16_t port,
               std::string transportProtocol,
               NodeContainer& remoteHostContainer,
               NetDeviceContainer& ueNetDev,
               Ptr<NrHelper> nrHelper,
               EpsBearer& bearer,
               Ptr<EpcTft> tft,
               bool isMx1,
               std::vector<Ptr<EpcTft>>& tfts,
               ApplicationContainer& serverApps,
               ApplicationContainer& clientApps,
               ApplicationContainer& pingApps)
{

    XrTrafficMixerHelper trafficMixerHelper;
    Ipv4Address ipAddress = ueIpIface.GetAddress(i, 0);
    if (g_paperTraffic)
    {
        // Paper model: one video stream per UE, frame-tagged packets.
        Ptr<XrFrameSource> srcApp = CreateObject<XrFrameSource>();
        srcApp->SetRemote(ipAddress, port);
        srcApp->SetVideoBitrate(g_videoBitrateMbps);
        srcApp->SetFps(g_fps);
        srcApp->SetFrameSizeShape(g_frameStdRatio, g_frameMinRatio, g_frameMaxRatio);
        srcApp->SetJitter(g_jitterStdMs, g_jitterLimitMs);
        srcApp->SetMtu(g_mtu);
        srcApp->SetUeIndex(i);
        srcApp->SetStopTime(MilliSeconds(g_appStartMs + g_appDurationMs));
        remoteHostContainer.Get(0)->AddApplication(srcApp);
        clientApps.Add(srcApp);

        // P4.2: only UEs served by the measured (centre) sites feed the statistics.
        // The outer UEs still get their traffic - they are just not measured.
        if (IsCenterUe(ueContainer.Get(i)->GetId()))
        {
            Ptr<XrFrameSink> sinkApp = CreateObject<XrFrameSink>();
            sinkApp->SetLocalPort(port);
            sinkApp->SetMtu(g_mtu);
            sinkApp->SetPdbMs(g_framePdbMs);
            std::ostringstream csvName;
            csvName << "frame_stats_port" << port << "_ue" << i << ".csv";
            sinkApp->SetCsvPath(csvName.str());
            std::ostringstream label;
            label << "port" << port << "-ue" << i;
            sinkApp->SetLabel(label.str());
            sinkApp->SetUeIndex(i);
            ueContainer.Get(i)->AddApplication(sinkApp);
            g_frameSinks.Add(sinkApp);
            g_ueDevicesForPhy.Add(ueNetDev.Get(i));
            ++g_centerUeCount;
        }
        else
        {
            ++g_outerUeCount;
        }

        nrHelper->ActivateDedicatedEpsBearer(ueNetDev.Get(i), bearer, tft);

        if (g_enablePing)
        {
            PingHelper pingPaper(ipAddress);
            pingApps.Add(pingPaper.Install(remoteHostContainer));
        }
        return;
    }


    trafficMixerHelper.ConfigureXr(config);
    auto it = XrPreconfig.find(config);

    std::vector<Address> addresses;
    std::vector<InetSocketAddress> localAddresses;
    for (uint j = 0; j < it->second.size(); j++)
    {
        addresses.emplace_back(InetSocketAddress(ipAddress, port + j));
        // The sink will always listen to the specified ports
        localAddresses.emplace_back(InetSocketAddress(Ipv4Address::GetAny(), port + j));
    }

    ApplicationContainer currentUeClientApps;
    currentUeClientApps.Add(
        trafficMixerHelper.Install(transportProtocol, addresses, remoteHostContainer.Get(0)));

    // Seed the ARP cache by pinging early in the simulation
    // This is a workaround until a static ARP capability is provided
    PingHelper ping(ipAddress);
    pingApps.Add(ping.Install(remoteHostContainer));

    Ptr<NetDevice> ueDevice = ueNetDev.Get(i);
    // Activate a dedicated bearer for the traffic type per node
    nrHelper->ActivateDedicatedEpsBearer(ueDevice, bearer, tft);
    // Activate a dedicated bearer for the traffic type per node
    if (isMx1)
    {
        nrHelper->ActivateDedicatedEpsBearer(ueDevice, bearer, tft);
    }
    else
    {
        NS_ASSERT(tfts.size() >= currentUeClientApps.GetN());
        for (uint32_t j = 0; j < currentUeClientApps.GetN(); j++)
        {
            nrHelper->ActivateDedicatedEpsBearer(ueDevice, bearer, tfts[j]);
        }
    }

    for (uint32_t j = 0; j < currentUeClientApps.GetN(); j++)
    {
        PacketSinkHelper dlPacketSinkHelper(transportProtocol, localAddresses.at(j));
        Ptr<Application> packetSink = dlPacketSinkHelper.Install(ueContainer.Get(i)).Get(0);
        serverApps.Add(packetSink);
    }
    clientApps.Add(currentUeClientApps);
}

// ---- P5.1: constant-gain antenna ----
// Used as the "indoor" UE antenna: the 20 dB penetration loss is applied as a
// negative receive gain, which attenuates the wanted signal and the interference
// alike and therefore leaves an indoor UE's SINR roughly unchanged while it needs
// about 20 dB more resources.
class FixedGainAntenna : public AntennaModel
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::FixedGainAntenna")
                                .SetParent<AntennaModel>()
                                .SetGroupName("Antenna")
                                .AddConstructor<FixedGainAntenna>()
                                .AddAttribute("GainDb",
                                              "Constant antenna gain in dB",
                                              DoubleValue(0.0),
                                              MakeDoubleAccessor(&FixedGainAntenna::m_gainDb),
                                              MakeDoubleChecker<double>());
        return tid;
    }

    double GetGainDb(Angles a) override
    {
        return m_gainDb;
    }

  private:
    double m_gainDb{0.0};
};

// ---- P4.2: lattice, scope helpers ----

// Hexagonal site lattice: ring 0 = the centre, then 6, 12, 18 ... sites per ring,
// ordered by azimuth inside each ring.  The old code placed sites 1..N on a single
// circle of radius ISD, which for numSites > 7 produced duplicated positions
// (site 7 landed on site 1, site 8 on site 2) - that bug is fixed here.
static std::vector<Vector>
BuildSitePositions(uint32_t numSites, double isd, double height, std::vector<uint32_t>* rings)
{
    std::vector<Vector> out;
    std::vector<uint32_t> outRings;
    out.push_back(Vector(0.0, 0.0, height));
    outRings.push_back(0);
    for (uint32_t ring = 1; out.size() < numSites; ++ring)
    {
        std::vector<std::pair<double, std::pair<int, int>>> layer;
        for (int q = -(int)ring; q <= (int)ring; ++q)
        {
            for (int r = -(int)ring; r <= (int)ring; ++r)
            {
                const int s = q + r;
                if (std::max(std::abs(q), std::max(std::abs(r), std::abs(s))) != (int)ring)
                {
                    continue;
                }
                const double x = isd * (q + r / 2.0);
                const double y = isd * (r * std::sqrt(3.0) / 2.0);
                layer.emplace_back(std::atan2(y, x), std::make_pair(q, r));
            }
        }
        std::sort(layer.begin(), layer.end());
        for (const auto& item : layer)
        {
            if (out.size() >= numSites)
            {
                break;
            }
            const int q = item.second.first;
            const int r = item.second.second;
            out.push_back(Vector(isd * (q + r / 2.0), isd * (r * std::sqrt(3.0) / 2.0), height));
            outRings.push_back(ring);
        }
    }
    if (rings)
    {
        *rings = outRings;
    }
    return out;
}

static bool
IsCenterSite(uint32_t site)
{
    if (g_statsRings < 0)
    {
        return true;
    }
    if (site >= g_siteRing.size())
    {
        return true;
    }
    return g_siteRing[site] <= static_cast<uint32_t>(g_statsRings);
}

static bool
IsCenterUe(uint32_t ueNodeId)
{
    if (g_statsRings < 0)
    {
        return true;
    }
    const auto it = g_ueServingSite.find(ueNodeId);
    if (it == g_ueServingSite.end())
    {
        return true; // legacy attach path: no per-UE site information
    }
    return IsCenterSite(it->second);
}

// Collect the gNB node ids / cell ids whose statistics are counted.
static void
BuildCenterSets(uint32_t numSites, uint32_t sectorsPerSite)
{
    g_centerGnbNodeIds.clear();
    g_centerCellIds.clear();
    for (uint32_t site = 0; site < numSites; ++site)
    {
        if (!IsCenterSite(site))
        {
            continue;
        }
        for (uint32_t k = 0; k < sectorsPerSite; ++k)
        {
            Ptr<NetDevice> nd = g_gnbDevSiteSector[site * sectorsPerSite + k];
            Ptr<NrGnbNetDevice> gnb = DynamicCast<NrGnbNetDevice>(nd);
            if (!gnb)
            {
                continue;
            }
            g_centerGnbNodeIds.insert(nd->GetNode()->GetId());
            g_centerCellIds.insert(gnb->GetCellId());
        }
    }
}

// ---- P4.1b: sectorization helpers ----

// The bearing angle lives in the element field pattern of the array, therefore
// the direction of maximum element gain IS the measured boresight of the antenna.
static double
AntennaBearingDeg(const Ptr<Object>& antenna)
{
    Ptr<UniformPlanarArray> upa = DynamicCast<UniformPlanarArray>(antenna);
    if (!upa)
    {
        return NAN;
    }
    double bestGain = -1.0;
    double bestAz = NAN;
    for (int az = -180; az < 180; ++az)
    {
        for (int inc = 60; inc <= 120; ++inc)
        {
            Angles a(az * M_PI / 180.0, inc * M_PI / 180.0);
            const auto fieldPattern = upa->GetElementFieldPattern(a);
            const double power =
                fieldPattern.first * fieldPattern.first + fieldPattern.second * fieldPattern.second;
            if (power > bestGain)
            {
                bestGain = power;
                bestAz = az;
            }
        }
    }
    return bestAz;
}

static void
ReportSectorBearings(uint32_t numSites, uint32_t sectorsPerSite)
{
    for (uint32_t site = 0; site < numSites; ++site)
    {
        for (uint32_t k = 0; k < sectorsPerSite; ++k)
        {
            Ptr<NetDevice> nd = g_gnbDevSiteSector[site * sectorsPerSite + k];
            Ptr<NrGnbNetDevice> gnb = DynamicCast<NrGnbNetDevice>(nd);
            NS_ABORT_MSG_IF(!gnb, "sector " << site << "/" << k << " is not a NrGnbNetDevice");
            Ptr<NrGnbPhy> phy = gnb->GetPhy(0);
            NS_ABORT_MSG_IF(!phy, "sector " << site << "/" << k << " has no NrGnbPhy");
            const Ptr<Object> antenna = phy->GetSpectrumPhy(0)->GetAntenna();
            std::cout << "[SECTOR] site " << site << " sector " << k << " cellId "
                      << gnb->GetCellId() << " bearing(measured) " << AntennaBearingDeg(antenna)
                      << " deg, nominal " << (360.0 * k / sectorsPerSite) << " deg" << std::endl;
        }
    }
}

// Co-located sectors all share one position, so "closest gNB" is ambiguous: pick
// the sector whose boresight points closest to the UE azimuth instead.
static void
AttachBySector(const NetDeviceContainer& ueDevs,
               const Ptr<NrHelper>& nrHelper,
               uint32_t numSites,
               uint32_t sectorsPerSite)
{
    std::vector<uint32_t> perSector(numSites * sectorsPerSite, 0);
    for (uint32_t i = 0; i < ueDevs.GetN(); ++i)
    {
        Ptr<NetDevice> ueDev = ueDevs.Get(i);
        const Vector uepos = ueDev->GetNode()->GetObject<MobilityModel>()->GetPosition();
        uint32_t bestSite = 0;
        double bestDist = std::numeric_limits<double>::infinity();
        for (uint32_t site = 0; site < numSites; ++site)
        {
            const double d =
                CalculateDistance(Vector(uepos.x, uepos.y, 0.0),
                                  Vector(g_sitePos[site].x, g_sitePos[site].y, 0.0));
            if (d < bestDist)
            {
                bestDist = d;
                bestSite = site;
            }
        }
        const double azimuth = std::atan2(uepos.y - g_sitePos[bestSite].y,
                                          uepos.x - g_sitePos[bestSite].x);
        uint32_t bestSector = 0;
        double bestDelta = std::numeric_limits<double>::infinity();
        for (uint32_t k = 0; k < sectorsPerSite; ++k)
        {
            const double bearing = 2.0 * M_PI * k / sectorsPerSite;
            const double delta = std::fabs(WrapToPi(azimuth - bearing));
            if (delta < bestDelta)
            {
                bestDelta = delta;
                bestSector = k;
            }
        }
        ++perSector[bestSite * sectorsPerSite + bestSector];
        g_ueServingSite[ueDev->GetNode()->GetId()] = bestSite;
        std::cout << "[ATTACH] ue node " << ueDev->GetNode()->GetId() << " -> site " << bestSite
                  << " sector " << bestSector << " (ue azimuth "
                  << (azimuth * 180.0 / M_PI) << " deg)" << std::endl;
        nrHelper->AttachToEnb(ueDev, g_gnbDevSiteSector[bestSite * sectorsPerSite + bestSector]);
    }
    std::cout << "[ATTACH] UEs per sector (site*sectors+sector=count):";
    for (uint32_t idx = 0; idx < perSector.size(); ++idx)
    {
        std::cout << " " << idx << "=" << perSector[idx];
    }
    std::cout << std::endl;
}

int
main(int argc, char* argv[])
{
    // set simulation time and mobility
    uint32_t appDuration = 60000;
    uint32_t simTimeMs = 0;
    uint32_t appStartTimeMs = 400;
    uint16_t numerology = 0;
    uint16_t arUeNum = 1;
    uint16_t vrUeNum = 1;
    uint16_t cgUeNum = 1;
    double centralFrequency = 4e9;
    double bandwidth = 5e6;
    double txPower = 41;
    bool isMx1 = true;
    bool useUdp = true;
    double distance = 450;
    uint32_t numSites = 1;   // 1 = single cell, 7 = centre + one hex ring
    double isd = 200;        // inter-site distance in metres
    double ueRadius = 0;     // 0 = auto
    uint32_t rngRun = 1;
    std::string trafficModel = "3gpp";
    std::string preset = "none";
    uint32_t pdcchSymbols = 0;
    std::string scheme = "rtsr";
    std::string tddPattern = "";
    uint32_t gnbRows = 4, gnbCols = 8;
    uint32_t ueRows = 1, ueCols = 1;
    double downtiltDeg = 0.0;
    double nfGnb = 5.0, nfUe = 7.0;
    bool sectorized = false;
    uint32_t numSectors = 3;
    int32_t siteRings = -1;
    int32_t statsRings = -1;
    uint32_t uePerCell = 0;
    double indoorRatio = 0.0;
    double indoorPenaltyDb = 20.0;
    double ueSpeedKmh = 0.0;
    uint32_t checkpointMs = 0;
    uint32_t warmupMs = 0;
    uint32_t progressMs = 0;
    bool enablePing = true;
    bool flowmonProbes = false;

    CommandLine cmd(__FILE__);
    cmd.AddValue("arUeNum", "The number of AR UEs", arUeNum);
    cmd.AddValue("vrUeNum", "The number of VR UEs", vrUeNum);
    cmd.AddValue("cgUeNum", "The number of CG UEs", cgUeNum);
    cmd.AddValue("numerology", "The numerology to be used.", numerology);
    cmd.AddValue("txPower", "Tx power to be configured to gNB", txPower);
    cmd.AddValue("frequency", "The system frequency", centralFrequency);
    cmd.AddValue("bandwidth", "The system bandwidth", bandwidth);
    cmd.AddValue("useUdp",
                 "if true, the NGMN applications will run over UDP connection, otherwise a TCP "
                 "connection will be used.",
                 useUdp);
    cmd.AddValue("distance",
                 "The radius of the disc (in meters) that the UEs will be distributed."
                 "Default value is 450m",
                 distance);
    cmd.AddValue("isMx1",
                 "if true M SDFs will be mapped to 1 DRB, otherwise the mapping will "
                 "be 1x1, i.e., 1 SDF to 1 DRB.",
                 isMx1);
    cmd.AddValue("rngRun", "Rng run random number.", rngRun);
    cmd.AddValue("numSites", "Number of gNBs (1 = single cell, 7 = centre + hex ring)", numSites);
    cmd.AddValue("isd", "Inter-site distance in metres", isd);
    cmd.AddValue("ueRadius", "UE drop radius in m (0 = auto)", ueRadius);
    cmd.AddValue("appDuration", "Duration of the application in milliseconds.", appDuration);
    cmd.AddValue("trafficModel",
                 "3gpp (default) or paper (10 Mbps / 60 FPS / truncated-Gaussian frames)",
                 trafficModel);
    cmd.AddValue("fps", "Video frame rate for trafficModel=paper", g_fps);
    cmd.AddValue("videoBitrate", "Per-UE video bitrate in Mbps for trafficModel=paper", g_videoBitrateMbps);
    cmd.AddValue("frameStd", "Frame-size std as a fraction of the mean", g_frameStdRatio);
    cmd.AddValue("frameMin", "Frame-size min as a fraction of the mean", g_frameMinRatio);
    cmd.AddValue("frameMax", "Frame-size max as a fraction of the mean", g_frameMaxRatio);
    cmd.AddValue("jitterStd", "Frame-arrival jitter std in ms", g_jitterStdMs);
    cmd.AddValue("jitterLimit", "Frame-arrival jitter truncation in ms", g_jitterLimitMs);
    cmd.AddValue("framePdb", "Frame PDB in ms (trafficModel=paper)", g_framePdbMs);
    cmd.AddValue("mtu", "Payload bytes per packet", g_mtu);
    cmd.AddValue("scheme", "rtsr | conventional (20 Mbps pure video, no model flow)",
                 scheme);
    cmd.AddValue("pdcchSymbols", "DL control (PDCCH) symbols, 0 = default",
                 pdcchSymbols);
    cmd.AddValue("tddPattern",
                 "TDD pattern, e.g. DDDSU or DL|DL|DL|S|UL (empty = default)",
                 tddPattern);
    cmd.AddValue("preset", "none | paperTable3", preset);
    cmd.AddValue("gnbRows", "gNB antenna rows", gnbRows);
    cmd.AddValue("gnbCols", "gNB antenna columns", gnbCols);
    cmd.AddValue("ueRows", "UE antenna rows", ueRows);
    cmd.AddValue("ueCols", "UE antenna columns", ueCols);
    cmd.AddValue("downtiltDeg", "gNB downtilt in degrees", downtiltDeg);
    cmd.AddValue("nfGnb", "gNB noise figure (dB)", nfGnb);
    cmd.AddValue("nfUe", "UE noise figure (dB)", nfUe);
    cmd.AddValue("sectorized",
                 "if true, every site hosts numSectors co-located gNBs with BearingAngle "
                 "0/120/240 deg (P4.1b)",
                 sectorized);
    cmd.AddValue("numSectors", "Number of sectors per site when --sectorized is used",
                 numSectors);
    cmd.AddValue("siteRings",
                 "If >= 0, lay the sites out on a hexagonal lattice with that many rings "
                 "(1 -> 7 sites, 2 -> 19, 3 -> 37) instead of the legacy --numSites layout",
                 siteRings);
    cmd.AddValue("statsRings",
                 "If >= 0, only sites within this many rings are measured; the outer rings "
                 "still transmit and therefore still interfere (P4.2)",
                 statsRings);
    cmd.AddValue("uePerCell",
                 "If > 0, drop this many UEs per sector around every site instead of one "
                 "disc of UEs around the centre (P4.2)",
                 uePerCell);
    cmd.AddValue("indoorRatio",
                 "Fraction of UEs placed indoors (P5.1).  Indoors UEs get an extra "
                 "penetration loss; 0 disables the split.",
                 indoorRatio);
    cmd.AddValue("indoorPenaltyDb", "Penetration loss for indoor UEs in dB", indoorPenaltyDb);
    cmd.AddValue("warmupMs",
                 "Exclude the first N ms from the frame statistics (warm-up: attach and "
                 "RRC setup); the traffic itself starts earlier (P6)",
                 warmupMs);
    cmd.AddValue("progressEveryMs",
                 "If > 0, write progress.txt (simulated time, wall time, ETA) this often; "
                 "cheap, unlike the full CSV checkpoint (P6)",
                 progressMs);
    cmd.AddValue("enablePing",
                 "Install the ping probe applications (diagnostic only; costs a little)",
                 enablePing);
    cmd.AddValue("flowmonProbes",
                 "Write the per-packet FlowMonitor probe section into the XML (large)",
                 flowmonProbes);
    cmd.AddValue("checkpointEveryMs",
                 "If > 0, flush every statistic to disk this often (ms) so a killed run "
                 "still leaves data; ns-3 cannot resume a run (P6)",
                 checkpointMs);
    cmd.AddValue("ueSpeedKmh",
                 "UE speed in km/h with a random direction per UE; 0 = stationary (P5.2)",
                 ueSpeedKmh);
    cmd.AddValue("simTimeMs", "Simulation length in milliseconds (default: appDuration).",
                 simTimeMs);
    cmd.Parse(argc, argv);

    g_tddPattern = tddPattern;
    g_pdcchSymbols = pdcchSymbols;
    g_sectorized = sectorized;
    g_numSectors = numSectors;
    g_siteRings = siteRings;
    g_statsRings = statsRings;
    g_uePerCell = uePerCell;
    g_checkpointMs = checkpointMs;
    g_warmupMs = warmupMs;
    g_progressMs = progressMs;
    g_enablePing = enablePing;
    g_flowmonProbes = flowmonProbes;
    if (g_siteRings >= 0)
    {
        numSites = 1 + 3 * static_cast<uint32_t>(g_siteRings) *
                           static_cast<uint32_t>(g_siteRings + 1);
    }
    if (g_statsRings > g_siteRings && g_siteRings >= 0)
    {
        NS_ABORT_MSG("statsRings (" << g_statsRings << ") exceeds siteRings (" << g_siteRings
                                    << "): there is no such outer ring");
    }
    if (g_uePerCell > 0)
    {
        const uint32_t sectors = g_sectorized ? g_numSectors : 1;
        const uint32_t total = numSites * sectors * g_uePerCell;
        NS_ABORT_MSG_IF(total > 65000, "uePerCell would create " << total << " UEs");
        arUeNum = static_cast<uint16_t>(total);
        vrUeNum = 0;
        cgUeNum = 0;
        std::cout << "[P4.2] uePerCell=" << g_uePerCell << " -> " << total << " UEs ("
                  << numSites << " sites x " << sectors << " sectors)" << std::endl;
    }
    g_conventional = (scheme == "conventional");
    if (g_conventional)
    {
        g_videoBitrateMbps = 20.0;
        std::cout << "[SCHEME] conventional: 20 Mbps pure video, no SR model flow"
                  << std::endl;
    }

    if (preset == "paperTable3")
    {
        // Table III of the paper (44 dBm per 20 MHz -> 44 dBm total, per decision #2)
        centralFrequency = 4.0e9;
        bandwidth = 100e6;
        numerology = 1;      // 30 kHz
        txPower = 44.0;
        isd = 200.0;
        gnbRows = 8;
        gnbCols = 8;         // 64 antenna elements
        ueRows = 2;
        ueCols = 2;          // 4 antenna elements
        downtiltDeg = 12.0;
        nfGnb = 5.0;
        nfUe = 9.0;
        g_pdcchSymbols = 2;
        std::cout << "[PRESET] paperTable3 applied: 4.0 GHz / 100 MHz / 30 kHz / "
                     "ISD 200 m / 64T4R / 44 dBm / downtilt 12 / NF 5,9"
                  << std::endl;
    }

    if (simTimeMs == 0)
    {
        simTimeMs = appDuration;
    }

    g_paperTraffic = (trafficModel == "paper");
    g_appStartMs = appStartTimeMs;
    g_appDurationMs = appDuration;
    if (g_paperTraffic)
    {
        std::cout << "[MODE] paper traffic model: " << g_videoBitrateMbps << " Mbps, " << g_fps
                  << " FPS, frame size " << g_frameMinRatio << "-" << g_frameMaxRatio
                  << " x mean (std " << g_frameStdRatio << "), jitter N(0," << g_jitterStdMs
                  << ") ms in [-" << g_jitterLimitMs << "," << g_jitterLimitMs << "], PDB "
                  << g_framePdbMs << " ms" << std::endl;
    }



    NS_ABORT_MSG_IF(appDuration < 1000, "The appDuration should be at least 1000ms.");
    NS_ABORT_MSG_IF(
        !vrUeNum && !arUeNum && !cgUeNum,
        "Activate at least one type of XR traffic by configuring the number of XR users");

    // simTimeMs defaults to appDuration when left at 0 (see cmd.Parse below)

    // Set simulation run number
    SeedManager::SetRun(rngRun);

    // setup the nr simulation
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    // simple band configuration and initialize
    CcBwpCreator ccBwpCreator;
    CcBwpCreator::SimpleOperationBandConf bandConf(centralFrequency,
                                                   bandwidth,
                                                   1,
                                                   BandwidthPartInfo::UMa_LoS);

    OperationBandInfo band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf);
    nrHelper->InitializeOperationBand(&band);
    BandwidthPartInfoPtrVector allBwps = CcBwpCreator::GetAllBwps({band});

    nrHelper->SetGnbPhyAttribute("TxPower", DoubleValue(txPower));
    nrHelper->SetGnbPhyAttribute("Numerology", UintegerValue(numerology));
    nrHelper->SetGnbPhyAttribute("NoiseFigure", DoubleValue(nfGnb));
    if (!g_tddPattern.empty())
    {
        // Must be an attribute: re-configuring the PHY after it started scheduling
        // slots (which is what a scheduled SetPattern at t=0 does) makes the PHY
        // schedule events in the past and aborts with "Negative delay".
        const std::string pattern = ConvertTddPattern(g_tddPattern);
        nrHelper->SetGnbPhyAttribute("Pattern", StringValue(pattern));
        std::cout << "[TDD] helper pattern = " << pattern << std::endl;
    }
    nrHelper->SetUePhyAttribute("TxPower", DoubleValue(23));
    nrHelper->SetUePhyAttribute("NoiseFigure", DoubleValue(nfUe));

    Config::SetDefault("ns3::LteRlcUm::MaxTxBufferSize", UintegerValue(500 * 1024));
    Config::SetDefault("ns3::LteEnbRrc::EpsBearerToRlcMapping",
                       EnumValue(useUdp ? LteEnbRrc::RLC_UM_ALWAYS : LteEnbRrc::RLC_AM_ALWAYS));

    // Use QoS-aware scheduling so the XR bearer (QCI 80) is served ahead of
    // the SR bearer (QCI 9) when radio resources are congested.
    nrHelper->SetSchedulerTypeId(TypeId::LookupByName("ns3::NrMacSchedulerTdmaQos"));
    if (g_pdcchSymbols > 0)
    {
        nrHelper->SetSchedulerAttribute("DlCtrlSymbols",
                                        UintegerValue(g_pdcchSymbols));
        std::cout << "[PDCCH] DL control symbols = " << g_pdcchSymbols << std::endl;
    }
    nrHelper->SetSchedulerAttribute("SchedLcAlgorithmType",
                                    TypeIdValue(NrMacSchedulerLcQos::GetTypeId()));

    nrHelper->SetGnbAntennaAttribute("NumRows", UintegerValue(gnbRows));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(gnbCols));
    nrHelper->SetGnbAntennaAttribute("AntennaElement",
                                     PointerValue(CreateObject<ThreeGppAntennaModel>()));
    nrHelper->SetGnbAntennaAttribute("AntennaHorizontalSpacing", DoubleValue(0.5));
    nrHelper->SetGnbAntennaAttribute("AntennaVerticalSpacing", DoubleValue(0.8));
    nrHelper->SetGnbAntennaAttribute("DowntiltAngle",
                                    DoubleValue(downtiltDeg * M_PI / 180.0));
    nrHelper->SetUeAntennaAttribute("NumRows", UintegerValue(ueRows));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(ueCols));
    nrHelper->SetUeAntennaAttribute("AntennaElement",
                                    PointerValue(CreateObject<IsotropicAntennaModel>()));

    // Beamforming method
    Ptr<IdealBeamformingHelper> idealBeamformingHelper = CreateObject<IdealBeamformingHelper>();
    idealBeamformingHelper->SetAttribute("BeamformingMethod",
                                         TypeIdValue(DirectPathBeamforming::GetTypeId()));
    nrHelper->SetBeamformingHelper(idealBeamformingHelper);

    Ptr<NrPointToPointEpcHelper> epcHelper = CreateObject<NrPointToPointEpcHelper>();
    nrHelper->SetEpcHelper(epcHelper);
    epcHelper->SetAttribute("S1uLinkDelay", TimeValue(MilliSeconds(0)));

    // Initialize nrHelper
    nrHelper->Initialize();

    NodeContainer gNbNodes;
    NodeContainer ueNodes;
    MobilityHelper mobility;
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");

    const double gNbHeight = 25;
    const double ueHeight = 1.5;

    const uint32_t sectorsPerSite = g_sectorized ? g_numSectors : 1;

    gNbNodes.Create(numSites * sectorsPerSite);
    ueNodes.Create(arUeNum + vrUeNum + cgUeNum);

    // Site positions come from the hexagonal lattice (ring 0 = centre, then 6, 12, 18
    // sites per ring).  Every sector of a site re-uses the same Vector, which is what
    // makes the three gNBs a sectorized site instead of three separate sites.
    g_sitePos = BuildSitePositions(numSites, isd, gNbHeight, &g_siteRing);
    std::cout << "[P4.2] " << numSites << " site(s) on "
              << (g_siteRings < 0 ? std::string("legacy") : std::to_string(g_siteRings))
              << " ring(s), " << (numSites * sectorsPerSite) << " cell(s)" << std::endl;
    Ptr<ListPositionAllocator> bsPositionAlloc = CreateObject<ListPositionAllocator>();
    for (uint32_t site = 0; site < numSites; ++site)
    {
        for (uint32_t k = 0; k < sectorsPerSite; ++k)
        {
            Vector pos = g_sitePos[site];
            if (g_sectorized)
            {
                const double offsetAz = 2.0 * M_PI * k / sectorsPerSite;
                pos.x += g_sectorOffsetM * std::cos(offsetAz);
                pos.y += g_sectorOffsetM * std::sin(offsetAz);
            }
            bsPositionAlloc->Add(pos);
        }
    }
    std::cout << "[SECTOR] " << numSites << " site(s) x " << sectorsPerSite
              << " sector(s) = " << (numSites * sectorsPerSite) << " gNB node(s)" << std::endl;
    mobility.SetPositionAllocator(bsPositionAlloc);
    mobility.Install(gNbNodes);

    if (g_uePerCell > 0)
    {
        // One independent disc per site: every cell then carries the same traffic,
        // which is what turns the outer rings into a real interference source.
        Ptr<ListPositionAllocator> ueSitePos = CreateObject<ListPositionAllocator>();
        Ptr<UniformRandomVariable> urv = CreateObject<UniformRandomVariable>();
        urv->SetAttribute("Min", DoubleValue(0.0));
        urv->SetAttribute("Max", DoubleValue(1.0));
        const double cellRadius = ueRadius > 0 ? ueRadius : isd / 2.0;
        for (uint32_t site = 0; site < numSites; ++site)
        {
            for (uint32_t k = 0; k < sectorsPerSite; ++k)
            {
                // Each sector gets exactly g_uePerCell UEs inside its own +-60 deg
                // wedge, so "UE per cell" is exact instead of a binomial draw.
                const double bearing = 2.0 * M_PI * k / sectorsPerSite;
                for (uint32_t j = 0; j < g_uePerCell; ++j)
                {
                    // sqrt() keeps the drop uniform over the disc area
                    const double rhoUe = cellRadius * std::sqrt(urv->GetValue());
                    const double angUe =
                        bearing + (urv->GetValue() - 0.5) * (2.0 * M_PI / sectorsPerSite);
                    ueSitePos->Add(Vector(g_sitePos[site].x + rhoUe * std::cos(angUe),
                                          g_sitePos[site].y + rhoUe * std::sin(angUe),
                                          ueHeight));
                }
            }
        }
        mobility.SetPositionAllocator(ueSitePos);
        std::cout << "[P4.2] " << ueNodes.GetN() << " UE(s) dropped in " << numSites
                  << " disc(s) of radius " << cellRadius << " m" << std::endl;
    }
    else
    {
        Ptr<RandomDiscPositionAllocator> ueDiscPositionAlloc =
            CreateObject<RandomDiscPositionAllocator>();
        ueDiscPositionAlloc->SetX(0.0);
        ueDiscPositionAlloc->SetY(0.0);
        ueDiscPositionAlloc->SetZ(ueHeight);
        double radius = ueRadius > 0 ? ueRadius : (numSites > 1 ? isd : 1.0);
        // RandomDiscPositionAllocator exposes the radius through the Rho attribute
        Ptr<UniformRandomVariable> rho = CreateObject<UniformRandomVariable>();
        rho->SetAttribute("Min", DoubleValue(0.0));
        rho->SetAttribute("Max", DoubleValue(radius));
        ueDiscPositionAlloc->SetAttribute("Rho", PointerValue(rho));
        mobility.SetPositionAllocator(ueDiscPositionAlloc);
    }

    if (ueSpeedKmh > 0.0)
    {
        // ConstantVelocity keeps the position set by the allocator and then moves the
        // node at a fixed velocity - exactly the paper's "3 km/h, random direction".
        mobility.SetMobilityModel("ns3::ConstantVelocityMobilityModel");
    }
    for (uint32_t i = 0; i < ueNodes.GetN(); i++)
    {
        mobility.Install(ueNodes.Get(i));
    }

    g_ueStartPos.clear();
    for (uint32_t i = 0; i < ueNodes.GetN(); i++)
    {
        g_ueStartPos.push_back(
            ueNodes.Get(i)->GetObject<MobilityModel>()->GetPosition());
    }

    if (ueSpeedKmh > 0.0)
    {
        Ptr<UniformRandomVariable> dirDraw = CreateObject<UniformRandomVariable>();
        dirDraw->SetAttribute("Min", DoubleValue(0.0));
        dirDraw->SetAttribute("Max", DoubleValue(2.0 * M_PI));
        const double v = ueSpeedKmh / 3.6; // km/h -> m/s
        uint32_t moving = 0;
        for (uint32_t i = 0; i < ueNodes.GetN(); i++)
        {
            Ptr<ConstantVelocityMobilityModel> mm =
                ueNodes.Get(i)->GetObject<ConstantVelocityMobilityModel>();
            NS_ABORT_MSG_IF(!mm, "UE " << i << " has no ConstantVelocityMobilityModel");
            const double dir = dirDraw->GetValue();
            mm->SetVelocity(Vector(v * std::cos(dir), v * std::sin(dir), 0.0));
            ++moving;
        }
        std::cout << "[P5.2] " << moving << " moving UE(s) at " << ueSpeedKmh
                  << " km/h (" << v << " m/s), random direction" << std::endl;
    }
    else
    {
        std::cout << "[P5.2] stationary UEs (ueSpeedKmh = 0)" << std::endl;
    }

    /*
     * Create various NodeContainer(s) for the different traffic types.
     * In ueArContainer, ueVrContainer, ueCgContainer, we will put
     * AR, VR, CG UEs, respectively.*/
    NodeContainer ueArContainer;
    NodeContainer ueVrContainer;
    NodeContainer ueCgContainer;

    for (auto j = 0; j < arUeNum; ++j)
    {
        Ptr<Node> ue = ueNodes.Get(j);
        ueArContainer.Add(ue);
    }
    for (auto j = arUeNum; j < arUeNum + vrUeNum; ++j)
    {
        Ptr<Node> ue = ueNodes.Get(j);
        ueVrContainer.Add(ue);
    }
    for (auto j = arUeNum + vrUeNum; j < arUeNum + vrUeNum + cgUeNum; ++j)
    {
        Ptr<Node> ue = ueNodes.Get(j);
        ueCgContainer.Add(ue);
    }

    // ---- P4.1b: install the gNBs, one batch per sector ----
    // Each gNB's antenna array is created inside InstallGnbDevice from the
    // helper's ObjectFactory, so setting BearingAngle between batches gives every
    // sector its own orientation without touching ns-3 internals.
    NetDeviceContainer gNbNetDev;
    g_gnbDevSiteSector.assign(numSites * sectorsPerSite, nullptr);
    for (uint32_t k = 0; k < sectorsPerSite; ++k)
    {
        const double bearingDeg = 360.0 * k / sectorsPerSite;
        // UniformPlanarArray::BearingAngle is checked against [-pi, pi], so 240 deg
        // has to be written as -120 deg (the same orientation after wrapping).
        const double bearingRad = WrapToPi(bearingDeg * M_PI / 180.0);
        nrHelper->SetGnbAntennaAttribute("BearingAngle", DoubleValue(bearingRad));
        NodeContainer batch;
        for (uint32_t site = 0; site < numSites; ++site)
        {
            batch.Add(gNbNodes.Get(site * sectorsPerSite + k));
        }
        NetDeviceContainer batchDev = nrHelper->InstallGnbDevice(batch, allBwps);
        for (uint32_t site = 0; site < numSites; ++site)
        {
            g_gnbDevSiteSector[site * sectorsPerSite + k] = batchDev.Get(site);
        }
        gNbNetDev.Add(batchDev);
        std::cout << "[SECTOR] installed " << batchDev.GetN() << " gNB(s) with bearing "
                  << bearingDeg << " deg (" << bearingRad << " rad)" << std::endl;
    }
    g_gnbDevices = gNbNetDev;
    BuildCenterSets(numSites, sectorsPerSite);
    ReportSectorBearings(numSites, sectorsPerSite);
    std::cout << "[SCOPE] sites=" << numSites << " cells=" << (numSites * sectorsPerSite)
              << " measured cells=" << g_centerCellIds.size()
              << " (statsRings=" << g_statsRings << ")" << std::endl;
    // ---- P5.1: install the AR UEs in an outdoor and an indoor batch ----
    // The UE antenna is created inside InstallUeDevice from the helper factory, so
    // the penetration loss has to be set between the two batches.
    NetDeviceContainer ueArNetDev;
    if (indoorRatio > 0.0)
    {
        NS_ABORT_MSG_IF(vrUeNum > 0 || cgUeNum > 0,
                        "indoorRatio currently supports only the AR container "
                        "(use --vrUeNum=0 --cgUeNum=0)");
        NodeContainer ueOutdoorContainer;
        NodeContainer ueIndoorContainer;
        g_indoorUeNodes.clear();
        Ptr<UniformRandomVariable> indoorDraw = CreateObject<UniformRandomVariable>();
        indoorDraw->SetAttribute("Min", DoubleValue(0.0));
        indoorDraw->SetAttribute("Max", DoubleValue(1.0));
        for (uint32_t j = 0; j < ueArContainer.GetN(); ++j)
        {
            if (indoorDraw->GetValue() < indoorRatio)
            {
                ueIndoorContainer.Add(ueArContainer.Get(j));
                g_indoorUeNodes.insert(ueArContainer.Get(j)->GetId());
            }
            else
            {
                ueOutdoorContainer.Add(ueArContainer.Get(j));
            }
        }
        g_indoorUeCount = ueIndoorContainer.GetN();
        nrHelper->SetUeAntennaAttribute("AntennaElement",
                                        PointerValue(CreateObject<IsotropicAntennaModel>()));
        NetDeviceContainer outDev = nrHelper->InstallUeDevice(ueOutdoorContainer, allBwps);
        Ptr<FixedGainAntenna> indoorAntenna = CreateObject<FixedGainAntenna>();
        indoorAntenna->SetAttribute("GainDb", DoubleValue(-indoorPenaltyDb));
        nrHelper->SetUeAntennaAttribute("AntennaElement", PointerValue(indoorAntenna));
        NetDeviceContainer inDev = nrHelper->InstallUeDevice(ueIndoorContainer, allBwps);
        // Reassemble in the original UE order: everything downstream (IP assignment,
        // attach, applications) indexes ueArNetDev by the UE index.
        uint32_t outIdx = 0;
        uint32_t inIdx = 0;
        for (uint32_t j = 0; j < ueArContainer.GetN(); ++j)
        {
            if (g_indoorUeNodes.count(ueArContainer.Get(j)->GetId()) > 0)
            {
                ueArNetDev.Add(inDev.Get(inIdx++));
            }
            else
            {
                ueArNetDev.Add(outDev.Get(outIdx++));
            }
        }
        std::cout << "[P5.1] indoor UEs = " << g_indoorUeCount << " / " << ueArContainer.GetN()
                  << " (" << (100.0 * g_indoorUeCount / ueArContainer.GetN())
                  << " %), penetration loss " << indoorPenaltyDb << " dB" << std::endl;
    }
    else
    {
        ueArNetDev = nrHelper->InstallUeDevice(ueArContainer, allBwps);
    }
    NetDeviceContainer ueVrNetDev = nrHelper->InstallUeDevice(ueVrContainer, allBwps);
    NetDeviceContainer ueCgNetDev = nrHelper->InstallUeDevice(ueCgContainer, allBwps);

    int64_t randomStream = 1;
    randomStream += nrHelper->AssignStreams(gNbNetDev, randomStream);
    randomStream += nrHelper->AssignStreams(ueArNetDev, randomStream);
    randomStream += nrHelper->AssignStreams(ueVrNetDev, randomStream);
    randomStream += nrHelper->AssignStreams(ueCgNetDev, randomStream);

    for (auto it = gNbNetDev.Begin(); it != gNbNetDev.End(); ++it)
    {
        DynamicCast<NrGnbNetDevice>(*it)->UpdateConfig();
    }
    for (auto it = ueArNetDev.Begin(); it != ueArNetDev.End(); ++it)
    {
        DynamicCast<NrUeNetDevice>(*it)->UpdateConfig();
    }
    for (auto it = ueVrNetDev.Begin(); it != ueVrNetDev.End(); ++it)
    {
        DynamicCast<NrUeNetDevice>(*it)->UpdateConfig();
    }
    for (auto it = ueCgNetDev.Begin(); it != ueCgNetDev.End(); ++it)
    {
        DynamicCast<NrUeNetDevice>(*it)->UpdateConfig();
    }

    // create the internet and install the IP stack on the UEs
    // get SGW/PGW and create a single RemoteHost
    Ptr<Node> pgw = epcHelper->GetPgwNode();
    NodeContainer remoteHostContainer;
    remoteHostContainer.Create(1);
    Ptr<Node> remoteHost = remoteHostContainer.Get(0);
    InternetStackHelper internet;
    internet.Install(remoteHostContainer);

    // connect a remoteHost to pgw. Setup routing too
    PointToPointHelper p2ph;
    p2ph.SetDeviceAttribute("DataRate", DataRateValue(DataRate("100Gb/s")));
    p2ph.SetDeviceAttribute("Mtu", UintegerValue(1000));
    p2ph.SetChannelAttribute("Delay", TimeValue(Seconds(0.000)));
    NetDeviceContainer internetDevices = p2ph.Install(pgw, remoteHost);
    Ipv4AddressHelper ipv4h;
    ipv4h.SetBase("1.0.0.0", "255.0.0.0");
    Ipv4InterfaceContainer internetIpIfaces = ipv4h.Assign(internetDevices);

    Ipv4StaticRoutingHelper ipv4RoutingHelper;
    Ptr<Ipv4StaticRouting> remoteHostStaticRouting =
        ipv4RoutingHelper.GetStaticRouting(remoteHost->GetObject<Ipv4>());
    remoteHostStaticRouting->AddNetworkRouteTo(Ipv4Address("7.0.0.0"), Ipv4Mask("255.0.0.0"), 1);
    internet.Install(ueNodes);

    Ipv4InterfaceContainer ueArIpIface;
    Ipv4InterfaceContainer ueVrIpIface;
    Ipv4InterfaceContainer ueCgIpIface;

    ueArIpIface = epcHelper->AssignUeIpv4Address(NetDeviceContainer(ueArNetDev));
    ueVrIpIface = epcHelper->AssignUeIpv4Address(NetDeviceContainer(ueVrNetDev));
    ueCgIpIface = epcHelper->AssignUeIpv4Address(NetDeviceContainer(ueCgNetDev));

    // Set the default gateway for the UEs
    for (uint32_t j = 0; j < ueNodes.GetN(); ++j)
    {
        Ptr<Ipv4StaticRouting> ueStaticRouting =
            ipv4RoutingHelper.GetStaticRouting(ueNodes.Get(j)->GetObject<Ipv4>());
        ueStaticRouting->SetDefaultRoute(epcHelper->GetUeDefaultGatewayAddress(), 1);
    }

    // attach UEs to the closest eNB
    if (g_sectorized)
    {
        AttachBySector(ueArNetDev, nrHelper, numSites, sectorsPerSite);
        AttachBySector(ueVrNetDev, nrHelper, numSites, sectorsPerSite);
        AttachBySector(ueCgNetDev, nrHelper, numSites, sectorsPerSite);
    }
    else
    {
        nrHelper->AttachToClosestEnb(ueArNetDev, gNbNetDev);
        nrHelper->AttachToClosestEnb(ueVrNetDev, gNbNetDev);
        nrHelper->AttachToClosestEnb(ueCgNetDev, gNbNetDev);
    }

    // P4.2: remember the IPs of the measured UEs - only after the attach step does
    // IsCenterUe() know which site a UE actually belongs to.  The FlowMonitor XML
    // export drops the addresses, so the centre-only L2 counters are built here.
    auto collectCenterIps = [](NetDeviceContainer& nd, Ipv4InterfaceContainer& ip) {
        for (uint32_t j = 0; j < nd.GetN(); ++j)
        {
            if (IsCenterUe(nd.Get(j)->GetNode()->GetId()))
            {
                g_centerUeIps.insert(ip.GetAddress(j, 0).Get());
            }
        }
    };
    collectCenterIps(ueArNetDev, ueArIpIface);
    collectCenterIps(ueVrNetDev, ueVrIpIface);
    collectCenterIps(ueCgNetDev, ueCgIpIface);
    std::cout << "[SCOPE] measured UE IPs=" << g_centerUeIps.size() << std::endl;

    // Install sink application
    ApplicationContainer serverApps;

    // configure the transport protocol to be used
    std::string transportProtocol;
    transportProtocol = useUdp == true ? "ns3::UdpSocketFactory" : "ns3::TcpSocketFactory";
    uint16_t dlPortArStart = 1121; // AR has 3 flows
    uint16_t dlPortArStop = 1124;
    uint16_t dlPortVrStart = 1131;
    uint16_t dlPortCgStart = 1141;

    // The bearer that will carry AR traffic
    EpsBearer arBearer(EpsBearer::NGBR_LOW_LAT_EMBB);
    Ptr<EpcTft> arTft = Create<EpcTft>();
    EpcTft::PacketFilter dlpfAr;
    std::vector<Ptr<EpcTft>> arTfts;

    if (isMx1)
    {
        dlpfAr.localPortStart = dlPortArStart;
        dlpfAr.localPortEnd = dlPortArStop;
        arTft->Add(dlpfAr);
    }
    else
    {
        // create 3 xrTfts for 1x1 mapping
        for (uint32_t i = 0; i < 3; i++)
        {
            Ptr<EpcTft> tempTft = Create<EpcTft>();
            dlpfAr.localPortStart = dlPortArStart + i;
            dlpfAr.localPortEnd = dlPortArStart + i;
            tempTft->Add(dlpfAr);
            arTfts.emplace_back(tempTft);
        }
    }
    // The bearer that will carry VR traffic
    EpsBearer vrBearer(EpsBearer::NGBR_LOW_LAT_EMBB);

    Ptr<EpcTft> vrTft = Create<EpcTft>();
    EpcTft::PacketFilter dlpfVr;
    dlpfVr.localPortStart = dlPortVrStart;
    dlpfVr.localPortEnd = dlPortVrStart;
    vrTft->Add(dlpfVr);

    // The bearer that will carry CG traffic
    EpsBearer cgBearer(EpsBearer::NGBR_LOW_LAT_EMBB);

    Ptr<EpcTft> cgTft = Create<EpcTft>();
    EpcTft::PacketFilter dlpfCg;
    dlpfCg.localPortStart = dlPortCgStart;
    dlpfCg.localPortEnd = dlPortCgStart;
    cgTft->Add(dlpfCg);

    // =============== 新增：RTSR 的 SR 模型低优先级承载 ===============
    // NGBR_VIDEO_TCP_DEFAULT 对应默认的 5QI 9，优先级远低于 XR 的 5QI 80+
    EpsBearer srBearer(EpsBearer::NGBR_VIDEO_TCP_DEFAULT);

    Ptr<EpcTft> srTft = Create<EpcTft>();
    EpcTft::PacketFilter srFilter;
    srFilter.localPortStart = 5000; // SR model destination port on the UE
    srFilter.localPortEnd = 5000;
    srTft->Add(srFilter);
    // ==============================================================

    // Install traffic generators
    ApplicationContainer clientApps;
    ApplicationContainer pingApps;

    std::ostringstream xrFileTag;

    for (uint32_t i = 0; i < ueArContainer.GetN(); ++i)
    {
        ConfigureXrApp(ueArContainer,
                       i,
                       ueArIpIface,
                       AR_M3,
                       dlPortArStart,
                       transportProtocol,
                       remoteHostContainer,
                       ueArNetDev,
                       nrHelper,
                       arBearer,
                       arTft,
                       isMx1,
                       arTfts,
                       serverApps,
                       clientApps,
                       pingApps);
    }
    // TODO for VR and CG of 2 flows Tfts and isMx1 have to be set. Currently they are
    // hardcoded for 1 flow
    for (uint32_t i = 0; i < ueVrContainer.GetN(); ++i)
    {
        ConfigureXrApp(ueVrContainer,
                       i,
                       ueVrIpIface,
                       VR_DL1,
                       dlPortVrStart,
                       transportProtocol,
                       remoteHostContainer,
                       ueVrNetDev,
                       nrHelper,
                       vrBearer,
                       vrTft,
                       1,
                       arTfts,
                       serverApps,
                       clientApps,
                       pingApps);
    }
    for (uint32_t i = 0; i < ueCgContainer.GetN(); ++i)
    {
        ConfigureXrApp(ueCgContainer,
                       i,
                       ueCgIpIface,
                       CG_DL1,
                       dlPortCgStart,
                       transportProtocol,
                       remoteHostContainer,
                       ueCgNetDev,
                       nrHelper,
                       cgBearer,
                       cgTft,
                       1,
                       arTfts,
                       serverApps,
                       clientApps,
                       pingApps);
    }

    pingApps.Start(MilliSeconds(100));
    pingApps.Stop(MilliSeconds(appStartTimeMs));

    // start server and client apps
    serverApps.Start(MilliSeconds(appStartTimeMs));
    clientApps.Start(MilliSeconds(appStartTimeMs));
    if (g_frameSinks.GetN() > 0)
    {
        g_frameSinks.Start(MilliSeconds(appStartTimeMs + g_warmupMs));
        if (g_warmupMs > 0)
        {
            std::cout << "[P6] warm-up " << g_warmupMs
                      << " ms excluded; frame statistics window starts at "
                      << (appStartTimeMs + g_warmupMs) << " ms" << std::endl;
        }
        g_frameSinks.Stop(MilliSeconds(simTimeMs - 1));
    }
    serverApps.Stop(MilliSeconds(simTimeMs));
    clientApps.Stop(MilliSeconds(appStartTimeMs + appDuration));

    FlowMonitorHelper flowmonHelper;
    NodeContainer endpointNodes;
    endpointNodes.Add(remoteHost);
    for (uint32_t j = 0; j < ueNodes.GetN(); ++j)
    {
        // P4.2: same scope as L1/L5, otherwise the IP loss would mix cells.
        if (IsCenterUe(ueNodes.Get(j)->GetId()))
        {
            endpointNodes.Add(ueNodes.Get(j));
        }
    }
    std::cout << "[SCOPE] measured UEs=" << g_centerUeCount << ", unmeasured (outer) UEs="
              << g_outerUeCount << std::endl;

    Ptr<ns3::FlowMonitor> monitor = flowmonHelper.Install(endpointNodes);
    monitor->SetAttribute("DelayBinWidth", DoubleValue(0.0001));
    monitor->SetAttribute("JitterBinWidth", DoubleValue(0.001));
    monitor->SetAttribute("PacketSizeBinWidth", DoubleValue(20));

    Simulator::Stop(MilliSeconds(simTimeMs));

    // =============== 新增：周期性发送 SR 模型 ===============
    NetDeviceContainer ueNetDev;
    ueNetDev.Add(ueArNetDev);
    ueNetDev.Add(ueVrNetDev);
    ueNetDev.Add(ueCgNetDev);

    Ipv4InterfaceContainer ueIpIface;
    ueIpIface.Add(ueArIpIface);
    ueIpIface.Add(ueVrIpIface);
    ueIpIface.Add(ueCgIpIface);

    uint32_t ueCount = ueNetDev.GetN();
    const uint32_t srUeCount = g_conventional ? 0 : ueCount;
    for (uint32_t i = 0; i < srUeCount; i++)
    {
        Ptr<NetDevice> ueDevice = ueNetDev.Get(i);
        // 激活 SR 模型的低优先级承载
        nrHelper->ActivateDedicatedEpsBearer(ueDevice, srBearer, srTft);

        // 获取 UE 的 IP
        Ipv4Address ueIp = ueIpIface.GetAddress(i, 0);

        PacketSinkHelper srSink("ns3::UdpSocketFactory",
                                InetSocketAddress(Ipv4Address::GetAny(), 5000));
        serverApps.Add(srSink.Install(ueNodes.Get(i)));

        // Send once every 6 seconds, starting just after the app and sink start.
        for (uint32_t t = 0; t < (appDuration / 6000); t++)
        {
            SendSrModel(remoteHost,
                        ueIp,
                        5000,
                        MilliSeconds(appStartTimeMs + 1 + t * 6000));
        }
    }
    // ======================================================

    if (g_paperTraffic)
    {
        // The RLC entities only exist after the UE attaches and the DRB is created,
        // so retry the wildcard connection until it succeeds (first success wins).
        Simulator::Schedule(MilliSeconds(0), &ApplyTddPattern);
        Simulator::Schedule(MilliSeconds(300), &TryConnectRlc);
        Simulator::Schedule(MilliSeconds(300), &TryConnectMacPhy);
    }

    if (g_checkpointMs > 0)
    {
        std::cout << "[P6] checkpoint every " << g_checkpointMs << " ms" << std::endl;
        Simulator::Schedule(MilliSeconds(g_checkpointMs), &Checkpoint);
    }
    if (g_progressMs > 0)
    {
        g_wallStart = std::chrono::steady_clock::now();
        Simulator::Schedule(MilliSeconds(g_progressMs), &ProgressTick);
        std::cout << "[P6] progress heartbeat every " << g_progressMs << " ms" << std::endl;
    }

    Simulator::Run();

    if (g_paperTraffic)
    {
        DumpRlcDrops(true);
        DumpMacPhy(true);
        DumpSourceFrames(true);
        WriteCheckpointMarker(true);
    }


    // Print per-flow statistics
    monitor->CheckForLostPackets();

    // Dump the raw FlowMonitor trace: per-flow counters plus the probe records
    // (one entry per packet), so the numbers printed below can be audited.
    // The per-packet probe section is huge and nothing reads it; the per-flow counters
    // that layer_stats.py uses are always written.
    flowmonHelper.SerializeToXmlFile("rtsr-flowmon.xml", true, g_flowmonProbes);
    std::cout << "\n[TRACE] FlowMonitor XML written to rtsr-flowmon.xml\n";
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowmonHelper.GetClassifier());
    FlowMonitor::FlowStatsContainer stats = monitor->GetFlowStats();

    double averageFlowThroughput = 0.0;
    double averageFlowDelay = 0.0;

    // L2 counters limited to the measured (centre) UEs: video is every flow that is
    // not the SR model port 5000.
    uint64_t l2VideoTx = 0;
    uint64_t l2VideoRx = 0;
    uint64_t l2ModelTx = 0;
    uint64_t l2ModelRx = 0;

    for (std::map<FlowId, FlowMonitor::FlowStats>::const_iterator i = stats.begin();
         i != stats.end();
         ++i)
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(i->first);
        if (g_statsRings >= 0 && g_centerUeIps.find(t.destinationAddress.Get()) == g_centerUeIps.end())
        {
            continue; // flow of an unmeasured UE: it still exists, it is just not counted
        }
        if (t.destinationPort == 5000)
        {
            l2ModelTx += i->second.txPackets;
            l2ModelRx += i->second.rxPackets;
        }
        else
        {
            l2VideoTx += i->second.txPackets;
            l2VideoRx += i->second.rxPackets;
        }
        std::stringstream protoStream;
        protoStream << (uint16_t)t.protocol;
        if (t.protocol == 6)
        {
            protoStream.str("TCP");
        }
        if (t.protocol == 17)
        {
            protoStream.str("UDP");
        }

        Time txDuration = MilliSeconds(appDuration);
        std::cout << "Flow " << i->first << " (" << t.sourceAddress << ":" << t.sourcePort << " -> "
                  << t.destinationAddress << ":" << t.destinationPort << ") proto "
                  << protoStream.str() << "\n";
        std::cout << "  Tx Packets: " << i->second.txPackets << "\n";
        std::cout << "  Tx Bytes:   " << i->second.txBytes << "\n";
        std::cout << "  TxOffered:  "
                  << ((i->second.txBytes * 8.0) / txDuration.GetSeconds()) * 1e-6 << " Mbps\n";
        std::cout << "  Rx Bytes:   " << i->second.rxBytes << "\n";

        if (i->second.rxPackets > 0)
        {
            // Measure the duration of the flow from receiver's perspective
            Time rxDuration = i->second.timeLastRxPacket - i->second.timeFirstTxPacket;
            averageFlowThroughput += ((i->second.rxBytes * 8.0) / rxDuration.GetSeconds()) * 1e-6;
            averageFlowDelay += 1000 * i->second.delaySum.GetSeconds() / i->second.rxPackets;

            double throughput = ((i->second.rxBytes * 8.0) / rxDuration.GetSeconds()) * 1e-6;
            double delay = 1000 * i->second.delaySum.GetSeconds() / i->second.rxPackets;
            double jitter = 1000 * i->second.jitterSum.GetSeconds() / i->second.rxPackets;

            std::cout << "  Throughput: " << throughput << " Mbps\n";
            std::cout << "  Mean delay:  " << delay << " ms\n";
            std::cout << "  Mean jitter:  " << jitter << " ms\n";
        }
        else
        {
            std::cout << "  Throughput:  0 Mbps\n";
            std::cout << "  Mean delay:  0 ms\n";
            std::cout << "  Mean upt:  0  Mbps \n";
            std::cout << "  Mean jitter: 0 ms\n";
        }
        std::cout << "  Rx Packets: " << i->second.rxPackets << "\n";
    }

    {
        std::ofstream l2("flowmon_center.csv");
        l2 << "metric,value\n";
        l2 << "video_tx_packets," << l2VideoTx << "\n";
        l2 << "video_rx_packets," << l2VideoRx << "\n";
        l2 << "model_tx_packets," << l2ModelTx << "\n";
        l2 << "model_rx_packets," << l2ModelRx << "\n";
        l2 << "measured_ues," << g_centerUeIps.size() << "\n";
        std::cout << "[L2] centre-only video tx/rx=" << l2VideoTx << "/" << l2VideoRx << " model "
                  << l2ModelTx << "/" << l2ModelRx << " (" << g_centerUeIps.size()
                  << " UE IPs)" << std::endl;
    }

    std::cout << "\n\n  Mean flow throughput: " << averageFlowThroughput / stats.size()
              << "Mbps \n";
    std::cout << "  Mean flow delay: " << averageFlowDelay / stats.size() << " ms\n";

    // P5.2 verification: 1) the speed actually achieved (displacement / elapsed time),
    // 2) the SINR time series of one reference UE.
    if (!g_ueStartPos.empty())
    {
        // The mobility models start moving at t=0 (mobility.Install happens during the
        // setup, not at the application start), so the elapsed time is the simulator
        // time itself - using (now - appStart) reported 3.21 km/h for a 3 km/h run.
        const double elapsed = Simulator::Now().GetSeconds();
        double sumSpeed = 0.0;
        uint32_t counted = 0;
        double moved = 0.0;
        for (uint32_t i = 0; i < ueNodes.GetN() && i < g_ueStartPos.size(); ++i)
        {
            const Vector p = ueNodes.Get(i)->GetObject<MobilityModel>()->GetPosition();
            const double d = CalculateDistance(Vector(p.x, p.y, 0.0),
                                               Vector(g_ueStartPos[i].x, g_ueStartPos[i].y, 0.0));
            if (elapsed > 0.0)
            {
                sumSpeed += d / elapsed;
                moved += d;
                ++counted;
            }
        }
        if (counted)
        {
            std::cout << "[P5.2] mean speed from displacement = " << (3.6 * sumSpeed / counted)
                      << " km/h over " << elapsed << " s (mean displacement "
                      << (moved / counted) << " m)" << std::endl;
        }
    }
    if (!g_wbSinrBuckets.empty())
    {
        std::ofstream wb("wb_data_sinr_buckets.csv");
        wb << "bucket_s,mean_sinr_db,samples\n";
        double bMin = 1e9;
        double bMax = -1e9;
        std::cout << "[P5.3] wideband DL-data SINR of ref UE cell=" << g_refCellId
                  << " rnti=" << g_refRnti << " (1 s buckets):";
        for (const auto& b : g_wbSinrBuckets)
        {
            const double mean = b.second.first / b.second.second;
            bMin = std::min(bMin, mean);
            bMax = std::max(bMax, mean);
            wb << b.first << "," << mean << "," << b.second.second << "\n";
            std::cout << " " << b.first << "s=" << mean;
        }
        std::cout << " (spread " << (bMax - bMin) << " dB)" << std::endl;
    }
    if (!g_ctrlSinrBuckets.empty())
    {
        std::ofstream cb("ctrl_sinr_buckets.csv");
        cb << "bucket_s,mean_sinr_db,samples\n";
        double bMin = 1e9;
        double bMax = -1e9;
        std::cout << "[P5.3] wideband DL-ctrl SINR of ref UE cell=" << g_refCellId
                  << " rnti=" << g_refRnti << " (1 s buckets):";
        for (const auto& b : g_ctrlSinrBuckets)
        {
            const double mean = b.second.first / b.second.second;
            bMin = std::min(bMin, mean);
            bMax = std::max(bMax, mean);
            cb << b.first << "," << mean << "," << b.second.second << "\n";
            std::cout << " " << b.first << "s=" << mean;
        }
        std::cout << " (spread " << (bMax - bMin) << " dB)" << std::endl;
    }
    if (!g_sinrTrace.empty())
    {
        std::ofstream tr("sinr_trace.csv");
        tr << "time_ms,sinr_db\n";
        for (const auto& s : g_sinrTrace)
        {
            tr << s.first << "," << s.second << "\n";
        }
        double mn = g_sinrTrace.front().second;
        double mx = mn;
        for (const auto& s : g_sinrTrace)
        {
            mn = std::min(mn, s.second);
            mx = std::max(mx, s.second);
        }
        // 1 s bucket means: the per-TB spread is dominated by the RB allocation, while
        // the bucket means show the slow channel drift that mobility causes.
        std::map<int, std::pair<double, int>> buckets;
        for (const auto& s : g_sinrTrace)
        {
            auto& b = buckets[static_cast<int>(s.first / 1000.0)];
            b.first += s.second;
            b.second += 1;
        }
        double bMin = 1e9;
        double bMax = -1e9;
        std::cout << "[P5.2] ref UE cell=" << g_refCellId << " rnti=" << g_refRnti
                  << " sinr samples=" << g_sinrTrace.size() << " per-TB range=" << (mx - mn)
                  << " dB; 1 s bucket means:";
        for (const auto& b : buckets)
        {
            const double mean = b.second.first / b.second.second;
            bMin = std::min(bMin, mean);
            bMax = std::max(bMax, mean);
            std::cout << " " << b.first << "s=" << mean;
        }
        std::cout << " (bucket spread " << (bMax - bMin) << " dB)" << std::endl;
    }

    Simulator::Destroy();
    return 0;
}
