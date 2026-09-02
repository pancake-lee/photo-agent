"""
    Agent Runtime 能力层，按「LLM 如何参与」分类组织：

        - resolve_trip.py 约束解析类：能力内 LLM（提示词抽取硬约束）+ 程序物化权威范围
        - retrieval.py    检索类：sql / rag / hybrid，能力自身不调 LLM
                           （sql 的自然语言转 SQL 封装在 text_to_sql 模块内，rag 纯向量）
        - photo_tools.py  程序工具类：Go 后端 HTTP 工具，全程无 LLM
        - creation.py     创作类：select_photos / write_post，能力内 LLM（提示词驱动）
        - common.py       跨能力共享辅助（执行护栏 / 能力内 LLM 调用 / 详情缓存）

    所有能力经 build_registry() 登记，以提示词里的能力清单提供给 decide 节点选择。
    每个能力的实现、工具描述、用户标题、决策提示、过程细节聚合在同一个代码块内，
    新增能力只需在对应分类文件补一个代码块并在此登记。
"""

import internal.runtime.capabilities.creation as creation
import internal.runtime.capabilities.photo_tools as photo_tools
import internal.runtime.capabilities.resolve_trip as resolve_trip
import internal.runtime.capabilities.retrieval as retrieval
import internal.runtime.registry as rt_registry


def build_registry() -> rt_registry.CapabilityRegistry:
    """登记 Runtime V1 的全部能力（顺序即 decide 提示词能力清单的顺序）。"""
    registry = rt_registry.CapabilityRegistry()
    capabilities = [
        resolve_trip.RESOLVE_TRIP,
        retrieval.SQL_SEARCH,
        retrieval.RAG_SEARCH,
        retrieval.HYBRID_SEARCH,
        photo_tools.FETCH_PHOTO_DETAILS,
        creation.SELECT_PHOTOS,
        creation.WRITE_POST,
    ]
    for capability in capabilities:
        registry.register(capability)
    return registry
