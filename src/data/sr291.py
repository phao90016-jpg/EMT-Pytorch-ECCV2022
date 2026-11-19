"""SR291 数据集（291 张图，超分早期工作常用的训练集）。
"""

from data import srdata

class SR291(srdata.SRData):
    def __init__(self, args, name='SR291', train=True, benchmark=False):
        super(SR291, self).__init__(args, name=name)

