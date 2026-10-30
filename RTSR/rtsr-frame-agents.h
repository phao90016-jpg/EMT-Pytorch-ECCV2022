// RTSR frame-level instrumentation.
//
// Why an in-payload frame header instead of a PacketTag: ns-3's RLC concatenates
// several SDUs into one PDU, and a tag attached to an SDU does not survive that
// concatenation (eight consecutive packets were observed carrying the same tag).
// Carrying the frame identity in the first 20 payload bytes is immune to
// fragmentation/concatenation and behaves like a real application framing.

#ifndef RTSR_FRAME_AGENTS_H
#define RTSR_FRAME_AGENTS_H

#include "ns3/application.h"
#include "ns3/inet-socket-address.h"
#include "ns3/ipv4-address.h"
#include "ns3/node.h"
#include "ns3/packet.h"
#include "ns3/random-variable-stream.h"
#include "ns3/simulator.h"
#include "ns3/socket.h"
#include "ns3/udp-socket-factory.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>

namespace ns3
{

struct FrameHeader
{
    static const uint32_t kSize = 22;

    uint16_t magic{0xA5C3};
    uint32_t frameId{0};
    uint16_t seq{0};
    uint16_t total{0};
    uint32_t frameBytes{0};
    uint64_t sendNs{0};

    void WriteTo(uint8_t* buf) const
    {
        std::memcpy(buf + 0, &magic, 2);
        std::memcpy(buf + 2, &frameId, 4);
        std::memcpy(buf + 6, &seq, 2);
        std::memcpy(buf + 8, &total, 2);
        std::memcpy(buf + 10, &frameBytes, 4);
        std::memcpy(buf + 14, &sendNs, 8);
    }

    bool ReadFrom(const uint8_t* buf)
    {
        std::memcpy(&magic, buf + 0, 2);
        if (magic != 0xA5C3)
        {
            return false;
        }
        std::memcpy(&frameId, buf + 2, 4);
        std::memcpy(&seq, buf + 6, 2);
        std::memcpy(&total, buf + 8, 2);
        std::memcpy(&frameBytes, buf + 10, 4);
        std::memcpy(&sendNs, buf + 14, 8);
        return true;
    }
};

class XrFrameSource : public Application
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::XrFrameSource")
                                .SetParent<Application>()
                                .SetGroupName("Applications")
                                .AddConstructor<XrFrameSource>();
        return tid;
    }

    void SetRemote(Ipv4Address dst, uint16_t port)
    {
        m_dst = dst;
        m_port = port;
    }

    void SetVideoBitrate(double mbps)
    {
        m_bitrateMbps = mbps;
    }

    void SetFps(double fps)
    {
        m_fps = fps;
    }

    void SetFrameSizeShape(double stdRatio, double minRatio, double maxRatio)
    {
        m_stdRatio = stdRatio;
        m_minRatio = minRatio;
        m_maxRatio = maxRatio;
    }

    void SetJitter(double stdMs, double limitMs)
    {
        m_jitterStdMs = stdMs;
        m_jitterLimitMs = limitMs;
    }

    void SetMtu(uint32_t mtu)
    {
        m_mtu = mtu;
    }

    void SetHardStop(Time t)
    {
        m_stopTime = t;
    }

  private:
    void StartApplication() override
    {
        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        m_socket->Connect(InetSocketAddress(m_dst, m_port));

        m_normal = CreateObject<NormalRandomVariable>();
        m_uniform = CreateObject<UniformRandomVariable>();
        m_normal->SetAttribute("Mean", DoubleValue(0.0));
        m_normal->SetAttribute("Variance", DoubleValue(m_jitterStdMs * m_jitterStdMs));

        m_framesSent = 0;
        m_bytesSent = 0;
        m_nominalTime = Seconds(0);
        ScheduleNextFrame();
    }

    void StopApplication() override
    {
        if (m_sendEvent.IsRunning())
        {
            Simulator::Cancel(m_sendEvent);
        }
        if (m_socket)
        {
            m_socket->Close();
        }
        std::cout << "[XrFrameSource] frames=" << m_framesSent << " bytes=" << m_bytesSent
                  << std::endl;
    }

    double TruncatedJitterMs()
    {
        for (int i = 0; i < 50; ++i)
        {
            double v = m_normal->GetValue();
            if (std::fabs(v) <= m_jitterLimitMs)
            {
                return v;
            }
        }
        return 0.0;
    }

    uint32_t DrawFrameBytes()
    {
        double meanBytes = m_bitrateMbps * 1e6 / 8.0 / m_fps;
        double sigma = m_stdRatio * meanBytes;
        double lo = m_minRatio * meanBytes;
        double hi = m_maxRatio * meanBytes;
        for (int i = 0; i < 100; ++i)
        {
            double v = meanBytes + m_uniform->GetValue(-1.0, 1.0) * sigma * 1.7320508;
            if (v >= lo && v <= hi)
            {
                return static_cast<uint32_t>(v);
            }
        }
        return static_cast<uint32_t>(meanBytes);
    }

    void ScheduleNextFrame()
    {
        double intervalMs = 1000.0 / m_fps;
        double jitter = TruncatedJitterMs();
        m_nominalTime += MilliSeconds(intervalMs);
        Time at = m_nominalTime + MilliSeconds(jitter);
        if (at < Simulator::Now())
        {
            at = Simulator::Now();
        }
        m_sendEvent = Simulator::Schedule(at - Simulator::Now(), &XrFrameSource::SendFrame, this);
    }

    void SendFrame()
    {
        uint32_t frameBytes = DrawFrameBytes();
        uint32_t total = (frameBytes + m_mtu - 1) / m_mtu;
        uint32_t remaining = frameBytes;
        uint64_t nowNs = Simulator::Now().GetNanoSeconds();

        for (uint32_t seq = 0; seq < total; ++seq)
        {
            uint32_t chunk = std::min(remaining, m_mtu);
            FrameHeader hdr;
            hdr.frameId = m_framesSent;
            hdr.seq = static_cast<uint16_t>(seq);
            hdr.total = static_cast<uint16_t>(total);
            hdr.frameBytes = frameBytes;
            hdr.sendNs = nowNs;

            uint8_t buf[FrameHeader::kSize];
            hdr.WriteTo(buf);

            Ptr<Packet> payload = Create<Packet>(chunk);
            Ptr<Packet> head = Create<Packet>(buf, FrameHeader::kSize);
            head->AddAtEnd(payload);

            m_socket->Send(head);
            m_bytesSent += chunk + FrameHeader::kSize;
            remaining -= chunk;
        }
        ++m_framesSent;
        ScheduleNextFrame();
    }

    Ptr<Socket> m_socket;
    Ptr<NormalRandomVariable> m_normal;
    Ptr<UniformRandomVariable> m_uniform;
    EventId m_sendEvent;

    Ipv4Address m_dst{"0.0.0.0"};
    uint16_t m_port{1000};
    double m_bitrateMbps{10.0};
    double m_fps{60.0};
    double m_stdRatio{0.105};
    double m_minRatio{0.5};
    double m_maxRatio{1.5};
    double m_jitterStdMs{2.0};
    double m_jitterLimitMs{4.0};
    uint32_t m_mtu{1400};
    Time m_nominalTime{Seconds(0)};
    Time m_stopTime{Seconds(0)};

    uint32_t m_framesSent{0};
    uint64_t m_bytesSent{0};
};

class XrFrameSink : public Application
{
  public:
    struct FrameRecord
    {
        uint32_t frameBytes{0};
        uint32_t expectedPkts{0};
        uint32_t pkts{0};
        uint64_t rxBytes{0};
        Time sourceStart{Seconds(0)};
        Time firstArrival{Seconds(0)};
        Time lastArrival{Seconds(0)};
        bool complete{false};
    };

    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::XrFrameSink")
                                .SetParent<Application>()
                                .SetGroupName("Applications")
                                .AddConstructor<XrFrameSink>();
        return tid;
    }

    void SetLocalPort(uint16_t port)
    {
        m_port = port;
    }

    void SetMtu(uint32_t mtu)
    {
        m_mtu = mtu; // recorded only; the header already carries the packet count
    }

    void SetPdbMs(double pdbMs)
    {
        m_pdbMs = pdbMs;
    }

    void SetCsvPath(std::string path)
    {
        m_csvPath = path;
    }

    void SetLabel(std::string label)
    {
        m_label = label;
    }

    void PrintSummary()
    {
        uint32_t seen = static_cast<uint32_t>(m_frames.size());
        double fsr = seen ? (100.0 * m_onTime / seen) : 0.0;
        std::cout << "[XrFrameSink " << m_label << "] frames=" << seen
                  << " complete=" << m_completed << " within_pdb=" << m_onTime
                  << " FSR=" << fsr << "% bad_hdr=" << m_badHdr << " pkts_rx=" << m_rxPackets
                  << std::endl;
    }

  private:
    void StartApplication() override
    {
        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), m_port));
        m_socket->SetRecvCallback(MakeCallback(&XrFrameSink::HandleRead, this));
    }

    void StopApplication() override
    {
        if (m_socket)
        {
            m_socket->Close();
        }
        WriteCsv();
        PrintSummary();
    }

    void WriteCsv()
    {
        std::ofstream out(m_csvPath);
        out << "frame_id,frame_bytes,expected_pkts,pkts,complete,source_ms,last_arrival_ms,"
               "e2e_ms,within_pdb\n";
        for (const auto& kv : m_frames)
        {
            const FrameRecord& r = kv.second;
            double last = r.lastArrival.GetMilliSeconds();
            double e2e = r.complete ? (r.lastArrival - r.sourceStart).GetMilliSeconds() : -1.0;
            bool ok = r.complete && e2e >= 0 && e2e <= m_pdbMs;
            out << kv.first << "," << r.frameBytes << "," << r.expectedPkts << "," << r.pkts << ","
                << (r.complete ? 1 : 0) << "," << r.sourceStart.GetMilliSeconds() << "," << last
                << "," << e2e << "," << (ok ? 1 : 0) << "\n";
        }
    }

    void HandleRead(Ptr<Socket> socket)
    {
        Ptr<Packet> pkt;
        while ((pkt = socket->Recv()))
        {
            ++m_rxPackets;
            m_rxBytes += pkt->GetSize();

            if (pkt->GetSize() < FrameHeader::kSize)
            {
                ++m_badHdr;
                continue;
            }
            uint8_t buf[FrameHeader::kSize];
            pkt->CopyData(buf, FrameHeader::kSize);
            FrameHeader hdr;
            if (!hdr.ReadFrom(buf))
            {
                ++m_badHdr;
                continue;
            }

            auto it = m_frames.find(hdr.frameId);
            if (it == m_frames.end())
            {
                FrameRecord rec;
                rec.frameBytes = hdr.frameBytes;
                rec.expectedPkts = hdr.total;
                rec.sourceStart = NanoSeconds(hdr.sendNs);
                rec.firstArrival = Simulator::Now();
                it = m_frames.emplace(hdr.frameId, rec).first;
            }
            FrameRecord& r = it->second;
            r.pkts++;
            r.rxBytes += pkt->GetSize();
            r.lastArrival = Simulator::Now();
            if (!r.complete && r.pkts >= r.expectedPkts)
            {
                r.complete = true;
                ++m_completed;
                double e2e = (r.lastArrival - r.sourceStart).GetMilliSeconds();
                if (e2e <= m_pdbMs)
                {
                    ++m_onTime;
                }
            }
        }
    }

    Ptr<Socket> m_socket;
    uint16_t m_port{1000};
    uint32_t m_mtu{1400};
    double m_pdbMs{10.0};
    std::string m_csvPath{"frame_stats.csv"};
    std::string m_label{"ue"};

    std::map<uint32_t, FrameRecord> m_frames;
    uint32_t m_completed{0};
    uint32_t m_onTime{0};
    uint32_t m_badHdr{0};
    uint64_t m_rxPackets{0};
    uint64_t m_rxBytes{0};
};

} // namespace ns3

#endif // RTSR_FRAME_AGENTS_H
