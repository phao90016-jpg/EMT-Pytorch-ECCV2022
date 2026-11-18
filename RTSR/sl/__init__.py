"""RTSR 系统级仿真器（阶段二/三）。

模块分工：
  config    —— 场景与模式参数（全包唯一来源）
  topology  —— 六边形站址、终端撒点与移动
  channel   —— 路损/阴影/穿透/波束/SINR
  link      —— SINR -> 频谱效率 -> TB 字节数
  scheduler —— TDMA / OFDMA 比例公平调度
  traffic   —— XR 帧业务与 10 ms PDB（FSR 口径在这里）
  metrics   —— 每 UE 的 FSR、满意率
  run_point —— 主循环入口（跑一个点）
"""
