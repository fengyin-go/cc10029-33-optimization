"""去重策略版本化与阈值重算领域逻辑。

需求落点：
- 阈值调整后按新阈值对「重新判定范围」内的历史记录重新判定，生成新的去重版本；
  已归档的原始采集批次保持只读，重算永远只产出新版本，不改写原始记录。
- 去重策略数据报告必须记录旧阈值、新阈值、重新判定范围；范围外记录不打新口径标记。
- 重复去重规则 = 判定口径（去重算法 + 业务键列）+ 阈值上限（相似阈值区间上界）。
- 同一业务键在新旧阈值下保留记录不同即口径冲突，下游始终只有一个 current 版本。
- 报告并发写入只允许一个提交成功；同一幂等键重复提交只生效一次，不产生第二条记录。
- 存储落地按报告确认的策略版本生成去重落地清单，版本不一致或重复落地一律拒绝。

本模块只做纯领域计算与带锁的状态流转，不直接依赖 FastAPI，方便单测与沿调用链追溯。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# 相似阈值允许的默认区间：重复去重只在该阈值区间内判定，口径 + 上限共同组成规则。
DEFAULT_LOWER = 0.5
DEFAULT_UPPER = 1.0
# 策略没有可解析的数值阈值时使用的历史口径默认值。
DEFAULT_OLD_THRESHOLD = 0.8

REPORT_STATUS_DRAFT = "待确认"
REPORT_STATUS_CONFIRMED = "已确认"
VERSION_FROZEN = "冻结版"
VERSION_LATEST = "最新版"
SCOPE_ALL = "全量历史批次"
CALIBER_NEW = "新口径"
CALIBER_OUT_OF_SCOPE = "未进入重算范围"

# 报告固定字段名：兼容既有重复去重接口，字段名与返回结构保持稳定，只做增量扩展。
REPORT_FIELDS = [
    "报告编号", "策略编号", "策略版本", "去重算法", "业务键列", "保留顺序",
    "旧阈值", "新阈值", "阈值下界", "阈值上界", "规则口径", "规则上限",
    "重新判定范围", "范围批次", "范围记录数", "覆盖记录数", "范围外记录数",
    "保留记录数", "重复记录数", "口径冲突数", "冻结状态", "当前版本",
    "报告状态", "幂等键", "数据来源", "生成时间",
]


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_threshold(value: Any, default: float) -> float:
    """把页面/种子里可能是文本的相似阈值解析成 float，无法解析时回退默认值。"""
    if value is None:
        return default
    try:
        return round(float(str(value).strip()), 4)
    except (TypeError, ValueError):
        return default


def similarity_between(left: dict[str, Any], right: dict[str, Any], algorithm: str) -> float:
    """两条采集记录在指定算法口径下的相似度，证据来自原始采集批次，不做任何改写。"""
    if algorithm == "精确匹配":
        return 1.0 if left.get("内容") == right.get("内容") else 0.0
    table = left.get("相似度") or {}
    key = "|".join(sorted((str(left["记录编号"]), str(right["记录编号"]))))
    if key in table:
        return round(float(table[key]), 4)
    table = right.get("相似度") or {}
    if key in table:
        return round(float(table[key]), 4)
    return 1.0 if left.get("内容") == right.get("内容") else 0.0


def _keep_index(order: str) -> int:
    # 最新采集优先时组内倒序挑选，其余情况按最早采集优先。
    return -1 if str(order or "").startswith("最新") else 0


def judge_records(
    records: list[dict[str, Any]],
    *,
    threshold: float,
    algorithm: str,
    keep_order: str,
) -> dict[str, Any]:
    """按一个确定的阈值口径对一批记录做去重判定。

    返回保留记录、重复记录（含重复证据）与按业务键分组的判定明细，
    同一份输入在新旧两个阈值下各跑一次即可对照口径变化。
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(str(record["业务键"]), []).append(record)

    kept: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    group_results: list[dict[str, Any]] = []
    pick = _keep_index(keep_order)

    for business_key, members in groups.items():
        ordered = sorted(members, key=lambda item: (str(item.get("采集批次", "")), str(item["记录编号"])))
        if pick == -1:
            ordered = list(reversed(ordered))
        kept_ids: list[str] = []
        dup_in_group: list[dict[str, Any]] = []
        for index, candidate in enumerate(ordered):
            matched: dict[str, Any] | None = None
            for keeper in ordered[:index]:
                if keeper["记录编号"] in kept_ids:
                    score = similarity_between(candidate, keeper, algorithm)
                    if score >= threshold:
                        matched = {"keeper": keeper, "score": score}
                        break
            if matched is None:
                kept_ids.append(str(candidate["记录编号"]))
                kept.append(candidate)
            else:
                evidence = {
                    "记录编号": candidate["记录编号"],
                    "业务键": business_key,
                    "采集批次": candidate.get("采集批次", ""),
                    "重复对象": matched["keeper"]["记录编号"],
                    "相似度": matched["score"],
                    "命中阈值": threshold,
                    "阈值区间": [DEFAULT_LOWER, DEFAULT_UPPER],
                    "判定口径": algorithm,
                    "规则上限": threshold,
                    "判定结果": "重复",
                }
                dup_in_group.append(evidence)
                duplicates.append(evidence)
        group_results.append({
            "业务键": business_key,
            "保留记录": kept_ids,
            "重复记录": [item["记录编号"] for item in dup_in_group],
            "重复证据": dup_in_group,
        })

    return {
        "threshold": threshold,
        "kept": kept,
        "duplicates": duplicates,
        "groups": group_results,
        "kept_keys": {key: group["保留记录"] for key, group in
                      ((item["业务键"], item) for item in group_results)},
    }


class DedupVersionService:
    """去重策略数据报告、去重版本与去重落地清单的写入口，全部在 store 锁内提交。"""

    def __init__(self, store: Any) -> None:
        self.store = store

    # ---- 基础读取 -------------------------------------------------------
    def _reports(self) -> list[dict[str, Any]]:
        return self.store.rows("dedup_reports")

    def _versions(self) -> list[dict[str, Any]]:
        return self.store.rows("dedup_versions")

    def _landing(self) -> list[dict[str, Any]]:
        return self.store.rows("dedup_landing")

    def _raw_records(self) -> list[dict[str, Any]]:
        # 原始采集批次只读：全程只读取，不提供任何写回路径。
        return self.store.rows("dedup_records")

    @staticmethod
    def _next_serial(rows: list[dict[str, Any]], prefix: str) -> str:
        biggest = 0
        for row in rows:
            code = str(row.get("报告编号") or row.get("落地清单编号") or "")
            if code.startswith(prefix):
                try:
                    biggest = max(biggest, int(code[len(prefix):]))
                except ValueError:
                    continue
        return f"{prefix}{biggest + 1:04d}"

    def _next_version_no(self, strategy_code: str) -> int:
        return sum(1 for row in self._versions() if row.get("策略编号") == strategy_code) + 1

    def list_reports(self, strategy_code: str | None = None) -> list[dict[str, Any]]:
        rows = self._reports()
        if strategy_code:
            rows = [row for row in rows if row.get("策略编号") == strategy_code]
        return sorted(rows, key=lambda item: int(item["id"]))

    def find_report(self, report_code: str) -> dict[str, Any] | None:
        for row in self._reports():
            if row.get("报告编号") == report_code:
                return row
        return None

    def list_versions(self, strategy_code: str | None = None) -> list[dict[str, Any]]:
        rows = self._versions()
        if strategy_code:
            rows = [row for row in rows if row.get("策略编号") == strategy_code]
        return sorted(rows, key=lambda item: int(item["id"]))

    def current_version(self, strategy_code: str) -> dict[str, Any] | None:
        for row in self._versions():
            if row.get("策略编号") == strategy_code and row.get("是否当前"):
                return row
        return None

    # ---- 重算报告 -------------------------------------------------------
    def submit_report(self, strategy: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str, int]:
        """按新阈值重算并提交去重策略数据报告。

        返回 (报告, 说明, http状态)。并发提交时只有一个能成功；同幂等键重复提交
        直接回传首次报告，不产生第二条记录。
        """
        strategy_code = str(strategy["策略编号"])
        algorithm = str(payload.get("去重算法") or strategy.get("去重算法") or "文本相似度")
        business_key_column = str(payload.get("业务键列") or strategy.get("业务键列") or "业务键")
        keep_order = str(payload.get("保留顺序") or strategy.get("保留顺序") or "最早采集优先")
        lower = parse_threshold(payload.get("阈值下界"), DEFAULT_LOWER)
        upper = parse_threshold(payload.get("阈值上界"), DEFAULT_UPPER)
        new_threshold = parse_threshold(payload.get("新阈值"), parse_threshold(strategy.get("相似阈值"), DEFAULT_OLD_THRESHOLD))
        old_threshold = parse_threshold(payload.get("旧阈值"), parse_threshold(strategy.get("相似阈值"), DEFAULT_OLD_THRESHOLD))
        idem_key = str(payload.get("幂等键") or f"IDEMP-{strategy_code}-{new_threshold}-{now_text()}")
        scope_batches = payload.get("范围批次") or []
        if isinstance(scope_batches, str):
            scope_batches = [item.strip() for item in scope_batches.split(",") if item.strip()]
        scope_label = str(payload.get("重新判定范围") or (SCOPE_ALL if not scope_batches else "指定采集批次"))

        if lower > upper:
            return None, "阈值下界不能大于阈值上界", 400
        if not (lower <= new_threshold <= upper):
            return None, f"新阈值 {new_threshold} 超出重复去重阈值区间 [{lower}, {upper}]，规则不成立", 400

        # 并发写入：同一策略的重算全过程独占，并发的第二份提交直接 409，只有一个成功。
        # 写锁的获取不经过 store.lock，慢重算在写锁内、store 事务外执行，
        # 保证并发请求能在计算开始前立即失败而不是被 store.lock 挡住。
        write_lock = self.store.dedup_lock(f"report:{strategy_code}")
        if not write_lock.acquire(blocking=False):
            return None, "去重策略数据报告正在并发写入，只允许一个提交成功", 409
        try:
            # 计算前先做幂等快查（重复提交直接返回，不触发重算）。
            with self.store.lock:
                for existing in self._reports():
                    if existing.get("幂等键") == idem_key:
                        existing["重复提交"] = True
                        return existing, "重复提交同一去重策略数据报告，只生效一次，未产生第二条记录", 200

            built = self._build_report(
                strategy=strategy, strategy_code=strategy_code, algorithm=algorithm,
                business_key_column=business_key_column, keep_order=keep_order,
                lower=lower, upper=upper, old_threshold=old_threshold,
                new_threshold=new_threshold, idem_key=idem_key,
                scope_batches=list(scope_batches), scope_label=scope_label,
            )
            if built[0] is None:
                return built

            # 计算完成后在 store 事务内落库，并复查幂等覆盖等待窗口。
            with self.store.lock:
                for existing in self._reports():
                    if existing.get("幂等键") == idem_key:
                        existing["重复提交"] = True
                        return existing, "重复提交同一去重策略数据报告，只生效一次，未产生第二条记录", 200
                report, version = built[0], built[1]
                self._demote_current_version_locked(strategy_code)
                self._reports().append(report)
                self._versions().append(version)
                return report, f"去重策略数据报告 {report['报告编号']} 已生成，去重版本 {report['策略版本']} 为当前版本", 201
        finally:
            write_lock.release()

    def _build_report(
        self, *, strategy: dict[str, Any], strategy_code: str, algorithm: str,
        business_key_column: str, keep_order: str, lower: float, upper: float,
        old_threshold: float, new_threshold: float, idem_key: str,
        scope_batches: list[str], scope_label: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, int]:
        # 读取原始批次与序号分配放在短事务里，避免慢计算长期持有 store.lock。
        with self.store.lock:
            raw_records = [dict(item) for item in self._raw_records()]
            if scope_batches:
                in_scope = [item for item in raw_records if item.get("采集批次") in scope_batches]
            else:
                in_scope = list(raw_records)
            if not in_scope:
                return None, None, "重新判定范围内没有可判定的采集记录", 400
            version_no = self._next_version_no(strategy_code)
            report_code = self._next_serial(self._reports(), "RPT-")
            report_id = len(self._reports()) + 1
            version_id = len(self._versions()) + 1
            out_of_scope = [item for item in raw_records if item not in in_scope]

        # 慢计算在写锁内、store 事务外执行，不阻塞其它线程的并发快速失败。
        old_result = judge_records(in_scope, threshold=old_threshold, algorithm=algorithm, keep_order=keep_order)
        new_result = judge_records(in_scope, threshold=new_threshold, algorithm=algorithm, keep_order=keep_order)

        # 口径冲突：同一业务键新旧阈值下保留记录集合不同。
        conflicts: list[dict[str, Any]] = []
        all_keys = sorted(set(old_result["kept_keys"]) | set(new_result["kept_keys"]))
        for key in all_keys:
            before = old_result["kept_keys"].get(key, [])
            after = new_result["kept_keys"].get(key, [])
            if before != after:
                conflicts.append({
                    "业务键": key,
                    "旧阈值保留记录": before,
                    "新阈值保留记录": after,
                    "冲突说明": "新旧口径保留记录不一致，下游以当前版本为准",
                })

        version_code = f"v{version_no}"
        rule_caliber = f"{algorithm}/{business_key_column}"
        report = {
            "id": report_id,
            "报告编号": report_code,
            "策略编号": strategy_code,
            "策略版本": version_code,
            "去重算法": algorithm,
            "业务键列": business_key_column,
            "保留顺序": keep_order,
            "旧阈值": old_threshold,
            "新阈值": new_threshold,
            "阈值下界": lower,
            "阈值上界": upper,
            "规则口径": rule_caliber,
            "规则上限": upper,
            "重新判定范围": scope_label,
            "范围批次": scope_batches,
            "范围记录数": len(raw_records),
            "覆盖记录数": len(in_scope),
            "范围外记录数": len(out_of_scope),
            "保留记录数": len(new_result["kept"]),
            "重复记录数": len(new_result["duplicates"]),
            "口径冲突数": len(conflicts),
            "冻结状态": "未冻结",
            "当前版本": True,
            "报告状态": REPORT_STATUS_DRAFT,
            "幂等键": idem_key,
            "数据来源": self.trace_source(strategy_code, report_code),
            "生成时间": now_text(),
            "重复提交": False,
            # 回看变化的明细数据：新旧保留记录、重复证据、冲突与范围外清单。
            "旧口径结果": {
                "阈值": old_threshold,
                "保留记录": [item["记录编号"] for item in old_result["kept"]],
                "重复证据": old_result["duplicates"],
            },
            "新口径结果": {
                "阈值": new_threshold,
                "保留记录": [item["记录编号"] for item in new_result["kept"]],
                "重复证据": new_result["duplicates"],
            },
            "口径冲突明细": conflicts,
            "范围外记录": [
                {"记录编号": item["记录编号"], "业务键": item["业务键"], "采集批次": item.get("采集批次", "")}
                for item in out_of_scope
            ],
        }

        version = {
            "id": version_id,
            "报告编号": report_code,
            "策略编号": strategy_code,
            "策略版本": version_code,
            "版本序号": version_no,
            "版本类型": VERSION_LATEST,
            "是否当前": True,
            "去重算法": algorithm,
            "相似阈值": new_threshold,
            "阈值下界": lower,
            "阈值上界": upper,
            "规则口径": rule_caliber,
            "规则上限": upper,
            "重新判定范围": scope_label,
            "范围批次": scope_batches,
            "保留记录数": len(new_result["kept"]),
            "重复记录数": len(new_result["duplicates"]),
            "口径冲突数": len(conflicts),
            "冻结状态": "未冻结",
            "来源": "阈值重算",
            "生成时间": now_text(),
        }
        return report, version, "", 201

    def _demote_current_version_locked(self, strategy_code: str) -> None:
        """落库前把旧当前版本转冻结版，保证同一策略只有一个当前版本。"""
        for row in self._versions():
            if row.get("策略编号") == strategy_code and row.get("是否当前"):
                row["是否当前"] = False
                row["版本类型"] = VERSION_FROZEN
                row["冻结状态"] = "已冻结"
        for report in self._reports():
            if report.get("策略编号") == strategy_code and report.get("当前版本"):
                report["当前版本"] = False

    def confirm_report(self, report_code: str) -> tuple[dict[str, Any] | None, str]:
        with self.store.lock:
            report = self.find_report(report_code)
            if report is None:
                return None, f"去重策略数据报告 {report_code} 不存在"
            report["报告状态"] = REPORT_STATUS_CONFIRMED
            return report, f"报告 {report_code} 已确认，策略版本 {report['策略版本']} 可用于存储落地"

    def set_current_version(self, strategy_code: str, version_code: str) -> tuple[dict[str, Any] | None, str]:
        """在冻结版与最新版之间取舍，切换后同一策略仍然只有一个当前版本。"""
        with self.store.lock:
            target = None
            for row in self._versions():
                if row.get("策略编号") == strategy_code and row.get("策略版本") == version_code:
                    target = row
                    break
            if target is None:
                return None, f"策略 {strategy_code} 不存在去重版本 {version_code}"
            for row in self._versions():
                if row.get("策略编号") == strategy_code:
                    row["是否当前"] = row is target
            for report in self._reports():
                if report.get("策略编号") == strategy_code:
                    report["当前版本"] = report.get("策略版本") == version_code
            # 版本类型（冻结版/最新版）是版本自身属性，切换当前标记时保持不变。
            return target, f"策略 {strategy_code} 当前去重版本已切换为 {version_code}（{target.get('版本类型')}）"

    # ---- 存储落地 -------------------------------------------------------
    def write_landing(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str, int]:
        """存储落地读取已确认报告生成去重落地清单，并回写到存储业务面。"""
        report_code = str(payload.get("报告编号") or "").strip()
        storage_code = str(payload.get("存储配置编号") or "").strip()
        expect_version = str(payload.get("策略版本") or "").strip()
        if not report_code or not storage_code:
            return None, "报告编号与存储配置编号必填", 400

        # 并发写入：同一报告的落地过程独占，写锁获取不经过 store.lock，
        # 并发第二份结果在任何计算之前即被拒绝。
        write_lock = self.store.dedup_lock(f"landing:{report_code}")
        if not write_lock.acquire(blocking=False):
            return None, "去重落地清单并发写入，存储落地拒绝第二份结果", 409
        try:
            # 短事务内完成校验与序号预留，慢计算放到事务外。
            with self.store.lock:
                report = self.find_report(report_code)
                if report is None:
                    return None, f"去重策略数据报告 {report_code} 不存在", 404
                if report.get("报告状态") != REPORT_STATUS_CONFIRMED:
                    return None, f"报告 {report_code} 尚未确认，不能生成去重落地清单", 409
                # 落地版本必须与报告中确认的策略版本一致。
                if expect_version and expect_version != report.get("策略版本"):
                    return None, (
                        f"落地版本 {expect_version} 与报告确认的策略版本 {report['策略版本']} 不一致，存储落地拒绝"
                    ), 409
                # 重复去重只允许一份落地结果，第二份结果直接拒绝。
                for row in self._landing():
                    if row.get("报告编号") == report_code and row.get("存储配置编号") == storage_code:
                        return None, f"报告 {report_code} 的去重落地清单已存在，存储落地拒绝第二份结果", 409
                landing_code = self._next_serial(self._landing(), "LAND-")
                next_id = len(self._landing()) + 1
                raw_records = [dict(item) for item in self._raw_records()]

            rows, summary = self._build_landing_rows(report, storage_code, landing_code, next_id, raw_records)

            # 最终落库事务内复查重复落地，覆盖计算等待窗口。
            with self.store.lock:
                for row in self._landing():
                    if row.get("报告编号") == report_code and row.get("存储配置编号") == storage_code:
                        return None, f"报告 {report_code} 的去重落地清单已存在，存储落地拒绝第二份结果", 409
                self._landing().extend(rows)
                return summary, f"去重落地清单 {landing_code} 已回写存储落地，版本与报告 {report['报告编号']} 一致", 201
        finally:
            write_lock.release()

    def _build_landing_rows(
        self, report: dict[str, Any], storage_code: str,
        landing_code: str, next_id: int, raw_records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        algorithm = report["去重算法"]
        keep_order = report["保留顺序"]
        threshold = report["新阈值"]
        scope_batches = report.get("范围批次") or []
        in_scope = [item for item in raw_records if not scope_batches or item.get("采集批次") in scope_batches]
        judged = judge_records(in_scope, threshold=threshold, algorithm=algorithm, keep_order=keep_order)
        kept_ids = {item["记录编号"] for item in judged["kept"]}
        evidence_index = {item["记录编号"]: item for item in judged["duplicates"]}
        archived_batches = {item.get("采集批次") for item in raw_records if item.get("归档只读")}
        landed_at = now_text()

        written: list[dict[str, Any]] = []
        serial = next_id - 1
        for record in raw_records:
            serial += 1
            record_id = record["记录编号"]
            in_range = record in in_scope
            if not in_range:
                # 未进入重算范围的记录不能标记为新口径结果。
                result, caliber, evidence = "未判定", CALIBER_OUT_OF_SCOPE, None
            elif record_id in kept_ids:
                result, caliber, evidence = "保留", CALIBER_NEW, None
            else:
                result, caliber, evidence = "重复", CALIBER_NEW, evidence_index.get(record_id)
            written.append({
                "id": serial,
                "落地清单编号": landing_code,
                "报告编号": report["报告编号"],
                "策略编号": report["策略编号"],
                "策略版本": report["策略版本"],
                "存储配置编号": storage_code,
                "记录编号": record_id,
                "业务键": record["业务键"],
                "采集批次": record.get("采集批次", ""),
                "归档只读": record.get("采集批次") in archived_batches,
                "判定结果": result,
                "相似阈值": threshold,
                "口径标记": caliber,
                "当前版本": True,
                "重复证据": evidence,
                "落地时间": landed_at,
            })

        summary = {
            "id": next_id,
            "落地清单编号": landing_code,
            "报告编号": report["报告编号"],
            "策略编号": report["策略编号"],
            "策略版本": report["策略版本"],
            "存储配置编号": storage_code,
            "明细条数": len(written),
            "保留条数": sum(1 for item in written if item["判定结果"] == "保留"),
            "重复条数": sum(1 for item in written if item["判定结果"] == "重复"),
            "范围外条数": sum(1 for item in written if item["判定结果"] == "未判定"),
            "落地时间": landed_at,
        }
        return written, summary

    def list_landing(
        self, *, report_code: str | None = None, storage_code: str | None = None,
        strategy_code: str | None = None, current_only: bool = False,
    ) -> list[dict[str, Any]]:
        rows = self._landing()
        if report_code:
            rows = [row for row in rows if row.get("报告编号") == report_code]
        if storage_code:
            rows = [row for row in rows if row.get("存储配置编号") == storage_code]
        if strategy_code:
            rows = [row for row in rows if row.get("策略编号") == strategy_code]
        if current_only:
            rows = [row for row in rows if row.get("当前版本")]
        return sorted(rows, key=lambda item: int(item["id"]))

    def trace_source(self, strategy_code: str, report_code: str | None = None) -> dict[str, Any]:
        """沿着重复去重调用链定位报告数据来源：原始批次 → 重算引擎 → 报告/版本 → 落地清单。"""
        raw_batches = sorted({item.get("采集批次", "") for item in self._raw_records()})
        chain = [
            {"层级": "重复去重策略", "对象": strategy_code, "说明": "阈值调整触发重算的策略入口"},
            {"层级": "原始采集批次", "对象": "、".join(raw_batches), "说明": "已归档批次只读，仅提供相似度证据"},
            {"层级": "重算判定引擎", "对象": "judge_records", "说明": "按新阈值区间与算法口径重新判定"},
            {"层级": "去重策略数据报告", "对象": report_code or "待生成", "说明": "记录旧阈值、新阈值与重新判定范围"},
            {"层级": "去重版本", "对象": "冻结版/最新版", "说明": "同一业务键冲突时仅一个当前版本"},
            {"层级": "存储落地清单", "对象": "dedup_landing", "说明": "按报告确认版本回写另一个业务面"},
        ]
        return {"调用链": "重复去重 → 阈值重算 → 数据报告 → 去重版本 → 存储落地", "链路明细": chain}
