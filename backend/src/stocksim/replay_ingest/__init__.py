"""模式 E「真实复盘」的离线数据管道（抓取、落盘、关卡包构建）。

运行时代码（api/services/models）不得导入本包；本包也不导入 stocksim 的其它子包。
"""

__all__ = ["BUILDER_VERSION", "PACK_FORMAT", "PACK_FORMAT_VERSION"]

BUILDER_VERSION = "1"
PACK_FORMAT = "stocksim-replay-pack"
PACK_FORMAT_VERSION = 1
