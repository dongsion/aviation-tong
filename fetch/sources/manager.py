"""
数据源管理器 - 读取配置、加载模块、按配置顺序聚合去重
"""
import importlib
import logging
import configparser
from typing import List, Dict, Any

from .base import DataSource, FetchResult, NotamRecord

logger = logging.getLogger(__name__)

# 支持的数据源映射
SOURCE_MAP = {
    'faa': 'fetch.sources.faa.client.FAASource',
}


def config_section_to_dict(config, section: str) -> Dict[str, str]:
    """将 ConfigParser 的某个 section 转为普通 dict"""
    if isinstance(config, configparser.ConfigParser):
        if config.has_section(section):
            return dict(config.items(section))
        return {}
    # 已经是 dict
    return config.get(section, {})


class SourceManager:
    """管理多个数据源的加载和聚合"""

    def __init__(self, config):
        self.config = config

    def get_enabled_sources(self) -> List[str]:
        """获取配置中启用的数据源列表"""
        ds_config = config_section_to_dict(self.config, 'DATA_SOURCES')
        enabled = ds_config.get('enabled', 'faa')
        return [s.strip().lower() for s in enabled.split(',') if s.strip()]

    def load_sources(self) -> List[DataSource]:
        """加载所有已启用的数据源"""
        enabled = self.get_enabled_sources()
        sources = []

        for name in enabled:
            if name not in SOURCE_MAP:
                logger.warning(f"未知数据源: {name}, 跳过")
                continue

            try:
                module_path, class_name = SOURCE_MAP[name].rsplit('.', 1)
                module = importlib.import_module(module_path)
                source_class = getattr(module, class_name)

                source_config = config_section_to_dict(self.config, name.upper())
                source = source_class(source_config)
                sources.append(source)
                logger.info(f"已加载数据源: {name}")

            except Exception as e:
                logger.error(f"加载数据源 {name} 失败: {e}")

        return sources

    def fetch_all(self, icao_codes: List[str]) -> FetchResult:
        """从所有数据源获取数据并聚合"""
        sources = self.load_sources()
        all_records = []
        seen_keys = set()  # 去重: (source, code)

        for source in sources:
            try:
                result = source.fetch(icao_codes)
                if result.is_valid:
                    for record in result.records:
                        key = (record.source, record.code)
                        if key not in seen_keys:
                            seen_keys.add(key)
                            all_records.append(record)
                else:
                    logger.warning(f"数据源 {source.name} 无有效数据")
            except Exception as e:
                logger.error(f"数据源 {source.name} 抓取失败: {e}")

        logger.info(f"聚合完成: 共 {len(all_records)} 条有效 NOTAM")
        return FetchResult(records=all_records, source="aggregated")
