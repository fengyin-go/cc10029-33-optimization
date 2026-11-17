"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

去重版本化重算用到的内部表（原始采集批次、数据报告、去重版本、落地清单）放在
独立的 _dedup_tables 注册表里：它们通过 rows() 读写，但不计入运营概览的业务模块。
所有跨表写入都在 self.lock 内完成，配合 flags 实现并发提交互斥。
"""
from __future__ import annotations

import threading
from typing import Any

from app.dedup_seed import DEDUP_SEED_TABLES
from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._dedup_tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in DEDUP_SEED_TABLES.items()
        }
        # 重入锁：服务层的多表事务（报告+版本、落地清单）在同一把锁内提交。
        self.lock = threading.RLock()
        # 按资源键互斥的写锁：报告与落地清单的并发第二份提交据此被拒绝。
        self._write_locks: dict[str, threading.Lock] = {}
        self._upgrade_dedup_strategy()

    def dedup_lock(self, key: str) -> threading.RLock:
        """返回某个去重资源（报告写入/落地写入）专属的互斥锁。

        注册表读写不经过 self.lock：否则一个线程在 self.lock 内做慢重算时，
        其它线程连获取写锁都会被挡在注册表查询上，无法在计算前快速失败。
        用 RLock 保证同线程可重入、跨线程仍互斥。
        """
        lock = self._write_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            self._write_locks[key] = lock
        return lock

    def _upgrade_dedup_strategy(self) -> None:
        """把已启用的去重策略补成真实阈值口径，让重算演示有明确的旧口径。"""
        for row in self._tables.get("dedup", []):
            if row.get("策略编号") == "DEDU-0003":
                row.update({
                    "业务键列": "业务键",
                    "去重算法": "文本相似度",
                    "对比窗口": "BATCH-A,BATCH-B,BATCH-C",
                    "相似阈值": 0.8,
                    "保留顺序": "最早采集优先",
                    "增量模式": "全量重算",
                    "生效批次": "BATCH-A",
                })

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        if module in self._dedup_tables:
            return self._dedup_tables[module]
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
