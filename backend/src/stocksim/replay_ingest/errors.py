"""本包的异常类型。"""

from __future__ import annotations


class SpecError(ValueError):
    """关卡规格不合法。"""


class BuildError(RuntimeError):
    """关卡包构建失败（原始数据缺失或不满足校验）。"""


class CollectError(ValueError):
    """抓存配置不合法（股票池文件、代码列表）。"""
