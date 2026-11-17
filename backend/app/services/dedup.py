"""重复去重业务规则：状态流转、字段校验与筛选口径都收在这里。

阈值重算、去重策略数据报告、去重版本与去重落地清单的领域逻辑在
app.dedup_versioning.DedupVersionService，本服务保持既有 CRUD 接口不变，
只额外暴露版本化能力，兼容既有重复去重接口的字段名与返回结构。
"""
from __future__ import annotations

from typing import Any

from app.dedup_versioning import DedupVersionService
from app.store import store

MODULE = "dedup"
LIST_FIELDS = ["策略编号", "业务键列", "去重算法", "对比窗口", "相似阈值", "保留顺序", "增量模式", "生效批次"]
REQUIRED_FIELDS = ["策略编号", "业务键列", "去重算法"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]


class DedupService:
    def __init__(self) -> None:
        # 版本化重算领域服务，沿着 重复去重 -> 阈值重算 -> 数据报告 -> 去重版本 -> 存储落地 调用链工作。
        self.versioning = DedupVersionService(store)

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("策略编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_strategy_by_code(self, strategy_code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("策略编号") == strategy_code:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"去重策略 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于重复去重可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"去重策略已{action}"
