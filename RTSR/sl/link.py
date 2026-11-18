"""SINR -> 频谱效率 -> 传输块大小（README 第 5.1 节第 4 步）。

用带编码间隙的香农公式，并封顶在 256QAM 的速率（7.4 bit/RE）：

    SE = alpha * log2(1 + SINR / gap)      再截断到 SE_MAX

  * 保守档：alpha=0.85、gap=1.0 dB（留一点实现余量）
  * 理想档：alpha=0.85、gap=0.0 dB（3GPP 链路级曲线的乐观端）

注意：模块文档里最初写的保守档参数是 alpha=0.75 / gap=3 dB，但代码里实际用的是
alpha=0.85 / gap=1.0 dB —— 后者才是把保守档容量标定到 ns-3 那 190 Mbps 的那一组，
以代码为准。

只算**单层**（64T4R 用 1 层）。多层 MIMO 是一个留待以后打开的开关
（实测开 rank 2 只 +0.8%，见 docs/stage1/06_ns3容量探查.md 第 24 节）。
"""
import numpy as np


class Link:
    SE_MAX = 7.4063          # 256QAM、码率约 0.93 时的每 RE 比特数

    def __init__(self, sc, mode):
        self.sc = sc
        self.mode = mode
        # 保守档必须复现 ns-3 阶段在 29-RB TB 上实测的约 7.3 bit/RE
        if mode.use_3gpp_curves:
            self.alpha, self.gap_db = 0.85, 0.0     # 理想档：直接用 3GPP 曲线
        else:
            self.alpha, self.gap_db = 0.85, 1.0     # 保守档：留 1 dB 实现余量
        self.n_layers = 1

    def se(self, sinr_db) -> np.ndarray:
        """SINR(dB) -> 频谱效率（bit/RE），已封顶在 SE_MAX。"""
        sinr_lin = 10.0 ** (np.asarray(sinr_db) / 10.0)
        gap = 10.0 ** (self.gap_db / 10.0)
        se = self.alpha * np.log2(1.0 + sinr_lin / gap) * self.n_layers
        return np.minimum(se, self.SE_MAX * self.n_layers)

    def tb_bytes(self, n_rb, sinr_db) -> np.ndarray:
        """给定 RB 数与 SINR 时，一次授权能装多少字节。

        每 RB = 12 个子载波 x 12 个数据符号（14 个符号减去 2 个 PDCCH 符号）。
        """
        n_re = np.asarray(n_rb) * 12 * 12      # 12 子载波 x 12 数据符号
        return n_re * self.se(sinr_db) / 8.0