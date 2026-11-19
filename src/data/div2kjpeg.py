"""DIV2K 的 JPEG 压缩版本（模拟真实传输中的压缩失真）。

按 name 里的质量因子（如 'DIV2K-Q60'）生成对应的压缩数据集。
"""

import os
from data import srdata
from data import div2k

class DIV2KJPEG(div2k.DIV2K):
    def __init__(self, args, name='', train=True, benchmark=False):
        self.q_factor = int(name.replace('DIV2K-Q', ''))
        super(DIV2KJPEG, self).__init__(
            args, name=name, train=train, benchmark=benchmark
        )

    def _set_filesystem(self, dir_data):
        self.apath = os.path.join(dir_data, 'DIV2K')
        self.dir_hr = os.path.join(self.apath, 'DIV2K_train_HR')
        self.dir_lr = os.path.join(
            self.apath, 'DIV2K_Q{}'.format(self.q_factor)
        )
        if self.input_large: self.dir_lr += 'L'
        self.ext = ('.png', '.jpg')

