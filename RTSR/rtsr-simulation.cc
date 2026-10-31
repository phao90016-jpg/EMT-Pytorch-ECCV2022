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

#include <cmath>
#include <cstring>
#include <fstream>
#include <map>
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

// ---- P0.3: RLC SDU drop accounting (TxDrop trace on the gNB RLC) ----
static uint64_t g_rlcDrops = 0;
static uint64_t g_rlcAttributed = 0;
static uint64_t g_rlcDroppedBytes = 0;
static std::map<uint32_t, uint64_t> g_rlcDropsPerFrame;

static void
RlcDropCallback(Ptr<const Packet> p)
{
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
                    ++g_rlcDropsPerFrame[hdr.frameId];
                }
                break;
            }
        }
    }
}

// Connect the gNB RLC TxDrop trace once the DRB exists; retry until it does.
static void
TryConnectRlc()
{
    static uint32_t attempts = 0;
    bool ok = Config::ConnectWithoutContextFailSafe(
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
static uint64_t g_macRetx = 0;
static uint64_t g_macTbBytes = 0;
static uint64_t g_phyTbs = 0;
static uint64_t g_phyCorrupt = 0;
static uint64_t g_phyBytes = 0;
static double g_sinrSum = 0.0;
static uint32_t g_sinrCount = 0;

static void
OnDlScheduling(NrSchedulingCallbackInfo info)
{
    if (info.m_tbSize && info.m_streamId <= 0)
    {
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
OnRxPacketTraceUe(RxPacketTraceParams params)
{
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
}

static void
DumpMacPhy()
{
    std::ofstream mac("mac_tb.csv");
    mac << "metric,value\n";
    mac << "scheduled_tbs," << g_macTbs << "\n";
    mac << "scheduled_bytes," << g_macTbBytes << "\n";
    mac << "retransmissions," << g_macRetx << "\n";

    std::ofstream phy("phy_tb.csv");
    phy << "metric,value\n";
    phy << "rx_tbs," << g_phyTbs << "\n";
    phy << "corrupt_tbs," << g_phyCorrupt << "\n";
    phy << "rx_bytes," << g_phyBytes << "\n";
    double bler = g_phyTbs ? 100.0 * g_phyCorrupt / g_phyTbs : 0.0;
    double meanSinr = g_sinrCount ? g_sinrSum / g_sinrCount : 0.0;
    phy << "bler_percent," << bler << "\n";
    phy << "mean_sinr_db," << meanSinr << "\n";

    std::cout << "[MAC] scheduled TBs=" << g_macTbs << " bytes=" << g_macTbBytes
              << " retx=" << g_macRetx << std::endl;
    std::cout << "[PHY] rx TBs=" << g_phyTbs << " corrupt=" << g_phyCorrupt << " BLER=" << bler
              << "% meanSINR=" << meanSinr << " dB" << std::endl;
}

// Try the MAC and PHY traces once the objects exist; retry a few times.
static void
TryConnectMacPhy()
{
    static uint32_t attempts = 0;
    bool mac = Config::ConnectWithoutContextFailSafe(
        "/NodeList/*/DeviceList/*/BandwidthPartMap/*/NrGnbMac/DlScheduling",
        MakeCallback(&OnDlScheduling));
    // The UE spectrum PHY is not reachable through Config paths, so connect it
    // directly: NrUeNetDevice -> NrUePhy -> NrSpectrumPhy -> trace.
    bool phy = false;
    uint32_t connected = 0;
    for (uint32_t i = 0; i < g_ueDevicesForPhy.GetN(); ++i)
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
        if (specPhy &&
            specPhy->TraceConnectWithoutContext("RxPacketTraceUe",
                                                MakeCallback(&OnRxPacketTraceUe)))
        {
            ++connected;
        }
    }
    phy = (connected > 0);
    if (phy)
    {
        std::cout << "[PHY] connected " << connected << " RxPacketTraceUe source(s)" << std::endl;
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

static void
DumpRlcDrops()
{
    std::ofstream out("rlc_drops.csv");
    out << "frame_id,dropped_sdus\n";
    for (const auto& kv : g_rlcDropsPerFrame)
    {
        out << kv.first << "," << kv.second << "\n";
    }
    std::cout << "[RLC] dropped SDUs=" << g_rlcDrops << " bytes=" << g_rlcDroppedBytes
              << " attributed=" << g_rlcAttributed << " frames_touched="
              << g_rlcDropsPerFrame.size() << std::endl;
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
        srcApp->SetStopTime(MilliSeconds(g_appStartMs + g_appDurationMs));
        remoteHostContainer.Get(0)->AddApplication(srcApp);
        clientApps.Add(srcApp);

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
        ueContainer.Get(i)->AddApplication(sinkApp);
        g_frameSinks.Add(sinkApp);
        g_ueDevicesForPhy.Add(ueNetDev.Get(i));

        nrHelper->ActivateDedicatedEpsBearer(ueNetDev.Get(i), bearer, tft);

        PingHelper pingPaper(ipAddress);
        pingApps.Add(pingPaper.Install(remoteHostContainer));
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
    cmd.AddValue("simTimeMs", "Simulation length in milliseconds (default: appDuration).",
                 simTimeMs);
    cmd.Parse(argc, argv);
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
    nrHelper->SetGnbPhyAttribute("NoiseFigure", DoubleValue(5));
    nrHelper->SetUePhyAttribute("TxPower", DoubleValue(23));
    nrHelper->SetUePhyAttribute("NoiseFigure", DoubleValue(7));

    Config::SetDefault("ns3::LteRlcUm::MaxTxBufferSize", UintegerValue(500 * 1024));
    Config::SetDefault("ns3::LteEnbRrc::EpsBearerToRlcMapping",
                       EnumValue(useUdp ? LteEnbRrc::RLC_UM_ALWAYS : LteEnbRrc::RLC_AM_ALWAYS));

    // Use QoS-aware scheduling so the XR bearer (QCI 80) is served ahead of
    // the SR bearer (QCI 9) when radio resources are congested.
    nrHelper->SetSchedulerTypeId(TypeId::LookupByName("ns3::NrMacSchedulerTdmaQos"));
    nrHelper->SetSchedulerAttribute("SchedLcAlgorithmType",
                                    TypeIdValue(NrMacSchedulerLcQos::GetTypeId()));

    nrHelper->SetGnbAntennaAttribute("NumRows", UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(8));
    nrHelper->SetGnbAntennaAttribute("AntennaElement",
                                     PointerValue(CreateObject<ThreeGppAntennaModel>()));
    nrHelper->SetGnbAntennaAttribute("AntennaHorizontalSpacing", DoubleValue(0.5));
    nrHelper->SetGnbAntennaAttribute("AntennaVerticalSpacing", DoubleValue(0.8));
    nrHelper->SetGnbAntennaAttribute("DowntiltAngle", DoubleValue(0 * M_PI / 180.0));
    nrHelper->SetUeAntennaAttribute("NumRows", UintegerValue(1));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(1));
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

    gNbNodes.Create(numSites);
    ueNodes.Create(arUeNum + vrUeNum + cgUeNum);

    Ptr<ListPositionAllocator> bsPositionAlloc = CreateObject<ListPositionAllocator>();
    bsPositionAlloc->Add(Vector(0.0, 0.0, gNbHeight));
    for (uint32_t site = 1; site < numSites; ++site)
    {
        // hex ring: sites 1..6 sit at the inter-site distance around the centre
        double angle = 2.0 * M_PI * (site - 1) / 6.0;
        bsPositionAlloc->Add(
            Vector(isd * std::cos(angle), isd * std::sin(angle), gNbHeight));
    }
    mobility.SetPositionAllocator(bsPositionAlloc);
    mobility.Install(gNbNodes);

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

    for (uint32_t i = 0; i < ueNodes.GetN(); i++)
    {
        mobility.Install(ueNodes.Get(i));
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

    NetDeviceContainer gNbNetDev = nrHelper->InstallGnbDevice(gNbNodes, allBwps);
    NetDeviceContainer ueArNetDev = nrHelper->InstallUeDevice(ueArContainer, allBwps);
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
    nrHelper->AttachToClosestEnb(ueArNetDev, gNbNetDev);
    nrHelper->AttachToClosestEnb(ueVrNetDev, gNbNetDev);
    nrHelper->AttachToClosestEnb(ueCgNetDev, gNbNetDev);

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
        g_frameSinks.Start(MilliSeconds(appStartTimeMs));
        g_frameSinks.Stop(MilliSeconds(simTimeMs - 1));
    }
    serverApps.Stop(MilliSeconds(simTimeMs));
    clientApps.Stop(MilliSeconds(appStartTimeMs + appDuration));

    FlowMonitorHelper flowmonHelper;
    NodeContainer endpointNodes;
    endpointNodes.Add(remoteHost);
    endpointNodes.Add(ueNodes);

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
    for (uint32_t i = 0; i < ueCount; i++)
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
        Simulator::Schedule(MilliSeconds(300), &TryConnectRlc);
        Simulator::Schedule(MilliSeconds(300), &TryConnectMacPhy);
    }

    Simulator::Run();

    if (g_paperTraffic)
    {
        DumpRlcDrops();
        DumpMacPhy();
    }


    // Print per-flow statistics
    monitor->CheckForLostPackets();

    // Dump the raw FlowMonitor trace: per-flow counters plus the probe records
    // (one entry per packet), so the numbers printed below can be audited.
    flowmonHelper.SerializeToXmlFile("rtsr-flowmon.xml", true, true);
    std::cout << "\n[TRACE] FlowMonitor XML written to rtsr-flowmon.xml\n";
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowmonHelper.GetClassifier());
    FlowMonitor::FlowStatsContainer stats = monitor->GetFlowStats();

    double averageFlowThroughput = 0.0;
    double averageFlowDelay = 0.0;

    for (std::map<FlowId, FlowMonitor::FlowStats>::const_iterator i = stats.begin();
         i != stats.end();
         ++i)
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(i->first);
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

    std::cout << "\n\n  Mean flow throughput: " << averageFlowThroughput / stats.size()
              << "Mbps \n";
    std::cout << "  Mean flow delay: " << averageFlowDelay / stats.size() << " ms\n";

    Simulator::Destroy();
    return 0;
}
