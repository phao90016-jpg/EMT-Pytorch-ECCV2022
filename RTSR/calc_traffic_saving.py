# 假设参数（基于 RTSR 论文）
duration = 60 # 仿真时间（秒）

# 1. 传统方案：直接传输 HD 视频（论文 Table II 中 20 Mbps）
hd_bitrate_mbps = 20
traditional_traffic_mb = (hd_bitrate_mbps * duration) / 8

# 2. RTSR 方案：传输 LD 视频（10 Mbps） + 周期性 SR 模型（781 KB / 6秒）
ld_bitrate_mbps = 10
ld_traffic_mb = (ld_bitrate_mbps * duration) / 8

model_size_mb = 781 / 1024
model_update_period = 6 # 秒
num_updates = duration // model_update_period
model_traffic_mb = num_updates * model_size_mb

rtsr_total_traffic_mb = ld_traffic_mb + model_traffic_mb

# 3. 计算节省比例
saved_traffic_mb = traditional_traffic_mb - rtsr_total_traffic_mb
saving_percent = (saved_traffic_mb / traditional_traffic_mb) * 100

print(f"=== RTSR 流量节省分析 ({duration}秒) ===")
print(f"传统 HD 方案总流量: {traditional_traffic_mb:.2f} MB")
print(f"RTSR LD 视频流量:   {ld_traffic_mb:.2f} MB")
print(f"RTSR SR 模型流量:   {model_traffic_mb:.2f} MB (发送了 {num_updates} 次)")
print(f"RTSR 总流量:        {rtsr_total_traffic_mb:.2f} MB")
print("-" * 40)
print(f"节省的总流量:       {saved_traffic_mb:.2f} MB")
print(f"总流量节省比例:     {saving_percent:.2f}%")
