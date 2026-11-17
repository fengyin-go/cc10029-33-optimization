"""去重版本化重算的示例数据。

模拟两张已归档的原始采集批次（只读）与一张在途批次，并给出采集时沉淀的
相似度证据。重算引擎只读取这些证据，不会回写或修改原始记录。
"""
from __future__ import annotations

from typing import Any

# 组内任意两条记录的相似度证据，键按记录编号排序后用 | 连接。
_SIMILARITY: dict[str, float] = {
    "R001|R002": 0.86,
    "R001|R003": 0.75,
    "R002|R003": 0.58,
    "R004|R005": 0.72,
    "R004|R006": 0.55,
    "R005|R006": 0.51,
    "R007|R008": 0.95,
    "R009|R010": 0.78,
    "R011|R012": 0.66,
}


def _record(
    record_id: str, business_key: str, batch: str, content: str, archived: bool
) -> dict[str, Any]:
    return {
        "id": int(record_id[1:]),
        "记录编号": record_id,
        "业务键": business_key,
        "采集批次": batch,
        "内容": content,
        "归档只读": archived,
        "相似度": dict(_SIMILARITY),
    }


# BATCH-A / BATCH-B 是阈值调整前已经归档的只读批次；BATCH-C 是阈值调整后的在途批次。
DEDUP_RECORDS: list[dict[str, Any]] = [
    _record("R001", "KEY-A", "BATCH-A", "商品A-主记录", True),
    _record("R002", "KEY-A", "BATCH-A", "商品A-重复记录", True),
    _record("R003", "KEY-A", "BATCH-B", "商品A-边缘记录", True),
    _record("R004", "KEY-B", "BATCH-A", "商品B-主记录", True),
    _record("R005", "KEY-B", "BATCH-A", "商品B-近似记录", True),
    _record("R006", "KEY-B", "BATCH-B", "商品B-独立记录", True),
    _record("R007", "KEY-C", "BATCH-B", "商品C-主记录", True),
    _record("R008", "KEY-C", "BATCH-B", "商品C-高度重复", True),
    _record("R009", "KEY-D", "BATCH-B", "商品D-旧记录", True),
    _record("R010", "KEY-D", "BATCH-C", "商品D-新记录", False),
    _record("R011", "KEY-E", "BATCH-C", "商品E-记录一", False),
    _record("R012", "KEY-E", "BATCH-C", "商品E-记录二", False),
]

# 重算产物表：启动时为空，全部由接口在锁内写入。
DEDUP_SEED_TABLES: dict[str, list[dict[str, Any]]] = {
    "dedup_records": DEDUP_RECORDS,
    "dedup_reports": [],
    "dedup_versions": [],
    "dedup_landing": [],
}
