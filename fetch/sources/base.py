"""
数据源基础接口 - 所有NOTAM数据源的统一接口定义
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class NotamRecord:
    """单条NOTAM记录的标准化结构"""
    code: str = ""           # NOTAM编号 (如 A1690/23)
    coordinates: str = ""    # 坐标字符串原文
    time: str = ""           # 有效时间区间
    platid: str = ""         # 平台ID/唯一标识
    raw_message: str = ""    # 原始NOTAM文本
    altitude: str = ""       # 高度限制
    source: str = "NOTAM"    # 数据来源
    fir: str = ""            # 飞行情报区
    notam_type: str = "other"  # NOTAM类型(用于颜色分类)


@dataclass
class FetchResult:
    """数据源抓取结果"""
    records: List[NotamRecord] = field(default_factory=list)
    source: str = "UNKNOWN"
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return len(self.records) > 0 and self.error is None


class DataSource:
    """数据源基类 - 子类需实现 fetch() 方法"""

    name = "base"

    def __init__(self, config: dict):
        self.config = config

    def fetch(self, icao_codes: List[str]) -> FetchResult:
        """抓取NOTAM数据 - 子类必须实现"""
        raise NotImplementedError("子类必须实现 fetch() 方法")
