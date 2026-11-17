"""去重版本化重算领域规则测试。

覆盖需求点：
- 新阈值重算生成新去重版本，已归档原始批次只读不改写；
- 报告必须记录旧阈值、新阈值、阈值区间与重新判定范围，范围外记录不打新口径；
- 口径 + 上限组成规则，阈值越界拒绝；
- 同一业务键新旧保留记录不同即口径冲突，下游只有一个当前版本；
- 并发写入只允许一个成功，同幂等键重复提交只生效一次；
- 存储落地版本必须与报告一致，第二份落地结果被拒绝；
- 存储业务面与去重业务面读取同一份落地清单。
"""
from __future__ import annotations

import threading
import time
import unittest
from collections import Counter

from app.dedup_versioning import DEFAULT_LOWER, DEFAULT_UPPER, DedupVersionService, judge_records
from app.services.dedup import DedupService
from app.services.storage import StorageService
from app.store import Store


def new_services() -> tuple[DedupService, StorageService, Store]:
    """每个用例使用独立 store，避免内存单例在用例间串数据。"""
    fresh = Store()
    dedup = DedupService()
    dedup.versioning = DedupVersionService(fresh)
    storage = StorageService()
    storage.dedup_versioning = DedupVersionService(fresh)
    return dedup, storage, fresh


class RecomputeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, _, self.store = new_services()
        self.strategy = self.svc.get_strategy_by_code("DEDU-0003")

    def test_report_records_thresholds_and_scope(self) -> None:
        report, message, code = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.7, "幂等键": "T1"})
        self.assertEqual(code, 201)
        self.assertEqual(report["旧阈值"], 0.8)
        self.assertEqual(report["新阈值"], 0.7)
        self.assertEqual(report["阈值下界"], DEFAULT_LOWER)
        self.assertEqual(report["阈值上界"], DEFAULT_UPPER)
        self.assertEqual(report["规则上限"], DEFAULT_UPPER)
        self.assertIn("文本相似度", report["规则口径"])
        self.assertEqual(report["重新判定范围"], "全量历史批次")
        self.assertEqual(report["覆盖记录数"], 12)
        self.assertEqual(report["范围外记录数"], 0)

    def test_threshold_out_of_interval_rejected(self) -> None:
        report, message, code = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 1.2, "阈值上界": 1.0, "幂等键": "T2"})
        self.assertIsNone(report)
        self.assertEqual(code, 400)
        self.assertIn("阈值区间", message)

    def test_scope_out_records_not_marked_new_caliber(self) -> None:
        report, _, code = self.svc.versioning.submit_report(
            self.strategy,
            {"新阈值": 0.6, "范围批次": ["BATCH-A", "BATCH-B"], "幂等键": "T3"})
        self.assertEqual(code, 201)
        self.assertEqual(report["覆盖记录数"], 9)
        self.assertEqual(report["范围外记录数"], 3)
        out_ids = {item["记录编号"] for item in report["范围外记录"]}
        self.assertEqual(out_ids, {"R010", "R011", "R012"})

        self.svc.versioning.confirm_report(report["报告编号"])
        summary, _, code = self.svc.versioning.write_landing(
            {"报告编号": report["报告编号"], "存储配置编号": "STOR-0003"})
        self.assertEqual(code, 201)
        rows = self.svc.versioning.list_landing(report_code=report["报告编号"])
        for row in rows:
            if row["记录编号"] in out_ids:
                self.assertEqual(row["口径标记"], "未进入重算范围")
                self.assertEqual(row["判定结果"], "未判定")
                self.assertIsNone(row["重复证据"])
            else:
                self.assertEqual(row["口径标记"], "新口径")

    def test_caliber_conflict_when_keeper_changes(self) -> None:
        report, _, code = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.7, "幂等键": "T4"})
        self.assertEqual(code, 201)
        conflict_keys = {item["业务键"] for item in report["口径冲突明细"]}
        # KEY-A/KEY-B/KEY-D 在新旧阈值下保留记录集合不同。
        self.assertEqual(conflict_keys, {"KEY-A", "KEY-B", "KEY-D"})
        for item in report["口径冲突明细"]:
            self.assertNotEqual(item["旧阈值保留记录"], item["新阈值保留记录"])

    def test_evidence_reviewable_before_and_after(self) -> None:
        report, _, _ = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.7, "幂等键": "T5"})
        old_dup = {item["记录编号"] for item in report["旧口径结果"]["重复证据"]}
        new_dup = {item["记录编号"] for item in report["新口径结果"]["重复证据"]}
        # 阈值收紧后重复集合扩大，且证据都可回看。
        self.assertTrue(new_dup > old_dup)
        evidence = report["新口径结果"]["重复证据"][0]
        for field in ["重复对象", "相似度", "命中阈值", "阈值区间", "判定口径"]:
            self.assertIn(field, evidence)

    def test_raw_archived_batches_remain_readonly(self) -> None:
        before = [dict(row) for row in self.store.rows("dedup_records")]
        self.svc.versioning.submit_report(self.strategy, {"新阈值": 0.7, "幂等键": "T6"})
        after = self.store.rows("dedup_records")
        self.assertEqual(before, after)
        self.assertTrue(all(row["归档只读"] for row in after if row["采集批次"] != "BATCH-C"))

    def test_only_one_current_version(self) -> None:
        r1, _, _ = self.svc.versioning.submit_report(self.strategy, {"新阈值": 0.7, "幂等键": "T7"})
        r2, _, _ = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.6, "范围批次": ["BATCH-A"], "幂等键": "T8"})
        versions = self.svc.versioning.list_versions("DEDU-0003")
        self.assertEqual(len(versions), 2)
        self.assertEqual(sum(1 for item in versions if item["是否当前"]), 1)
        self.assertTrue(self.svc.versioning.current_version("DEDU-0003")["策略版本"], r2["策略版本"])
        # 切回冻结版后仍然只有一个当前版本，且类型保留冻结版。
        target, message = self.svc.versioning.set_current_version("DEDU-0003", r1["策略版本"])
        self.assertTrue(target["是否当前"])
        self.assertEqual(target["版本类型"], "冻结版")
        self.assertEqual(
            sum(1 for item in self.svc.versioning.list_versions("DEDU-0003") if item["是否当前"]), 1)


class IdempotencyAndConcurrencyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, _, _ = new_services()
        self.strategy = self.svc.get_strategy_by_code("DEDU-0003")

    def test_duplicate_submit_takes_effect_once(self) -> None:
        first, _, code = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.7, "幂等键": "DUP-1"})
        self.assertEqual(code, 201)
        second, message, code2 = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.7, "幂等键": "DUP-1"})
        self.assertEqual(code2, 200)
        self.assertEqual(second["报告编号"], first["报告编号"])
        self.assertTrue(second["重复提交"])
        self.assertEqual(len(self.svc.versioning.list_reports()), 1)

    def test_concurrent_submit_only_one_succeeds(self) -> None:
        import app.dedup_versioning as module

        original = module.judge_records
        entered = threading.Event()
        release = threading.Event()

        def slow_judge(*args, **kwargs):
            entered.set()
            release.wait(timeout=2)
            return original(*args, **kwargs)

        module.judge_records = slow_judge
        results: list[int] = []
        second_done = threading.Event()
        try:
            def first_worker() -> None:
                _, _, code = self.svc.versioning.submit_report(
                    self.strategy, {"新阈值": 0.7, "幂等键": "C1"})
                results.append(code)

            first = threading.Thread(target=first_worker)
            first.start()
            # 等到线程 A 确实进入重算（持有写锁）后，再让线程 B 并发提交。
            self.assertTrue(entered.wait(timeout=2))

            def second_worker() -> None:
                try:
                    _, _, code = self.svc.versioning.submit_report(
                        self.strategy, {"新阈值": 0.7, "幂等键": "C2"})
                    results.append(code)
                finally:
                    second_done.set()

            second = threading.Thread(target=second_worker)
            second.start()
            # 线程 B 命中并发互斥会立即返回；等它结束后再放行 A 的慢重算。
            self.assertTrue(second_done.wait(timeout=2))
            release.set()
            first.join(timeout=2)
        finally:
            module.judge_records = original

        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(len(self.svc.versioning.list_reports()), 1)

    def test_rejected_concurrent_request_can_retry_afterward(self) -> None:
        # 409 是并发保护而非永久拒绝：窗口结束后用新幂等键重试应当成功。
        first, _, code = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.7, "幂等键": "R-A"})
        self.assertEqual(code, 201)
        retry, _, retry_code = self.svc.versioning.submit_report(
            self.strategy, {"新阈值": 0.65, "幂等键": "R-B"})
        self.assertEqual(retry_code, 201)
        self.assertNotEqual(retry["报告编号"], first["报告编号"])

    def test_same_idempotency_key_concurrent_single_record(self) -> None:
        import app.dedup_versioning as module

        original = module.judge_records
        entered = threading.Event()
        release = threading.Event()

        def slow_judge(*args, **kwargs):
            entered.set()
            release.wait(timeout=2)
            return original(*args, **kwargs)

        module.judge_records = slow_judge
        codes: list[int] = []
        others_done = threading.Event()
        remaining = {"count": 3}
        try:
            def worker() -> None:
                try:
                    _, _, code = self.svc.versioning.submit_report(
                        self.strategy, {"新阈值": 0.65, "幂等键": "SAME"})
                    codes.append(code)
                finally:
                    remaining["count"] -= 1
                    if remaining["count"] == 0:
                        others_done.set()

            first = threading.Thread(target=worker)
            first.start()
            self.assertTrue(entered.wait(timeout=2))
            others = [threading.Thread(target=worker) for _ in range(3)]
            for thread in others:
                thread.start()
            # 三个并发线程都会被互斥/幂等立即处理，等它们结束再放行慢重算。
            self.assertTrue(others_done.wait(timeout=2))
            release.set()
            first.join(timeout=2)
            for thread in others:
                thread.join(timeout=2)
        finally:
            module.judge_records = original

        # 并发下一个成功(201)，其余被并发保护拒绝(409)；无论如何同键只有一条报告。
        self.assertEqual(codes.count(201), 1)
        self.assertTrue(all(code in (200, 201, 409) for code in codes))
        self.assertEqual(
            sum(1 for item in self.svc.versioning.list_reports() if item["幂等键"] == "SAME"), 1)


class LandingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dedup, self.storage, self.store = new_services()
        self.strategy = self.dedup.get_strategy_by_code("DEDU-0003")
        self.report, _, _ = self.dedup.versioning.submit_report(
            self.strategy, {"新阈值": 0.7, "幂等键": "L1"})

    def test_landing_requires_confirmed_report(self) -> None:
        summary, message, code = self.dedup.versioning.write_landing(
            {"报告编号": self.report["报告编号"], "存储配置编号": "STOR-0003"})
        self.assertIsNone(summary)
        self.assertEqual(code, 409)

    def test_landing_version_must_match_report(self) -> None:
        self.dedup.versioning.confirm_report(self.report["报告编号"])
        summary, message, code = self.dedup.versioning.write_landing({
            "报告编号": self.report["报告编号"],
            "存储配置编号": "STOR-0003",
            "策略版本": "v999",
        })
        self.assertIsNone(summary)
        self.assertEqual(code, 409)
        self.assertIn("不一致", message)

    def test_second_landing_result_rejected(self) -> None:
        self.dedup.versioning.confirm_report(self.report["报告编号"])
        first, _, code = self.dedup.versioning.write_landing(
            {"报告编号": self.report["报告编号"], "存储配置编号": "STOR-0003",
             "策略版本": self.report["策略版本"]})
        self.assertEqual(code, 201)
        second, message, code2 = self.dedup.versioning.write_landing(
            {"报告编号": self.report["报告编号"], "存储配置编号": "STOR-0003"})
        self.assertIsNone(second)
        self.assertEqual(code2, 409)
        self.assertIn("拒绝第二份结果", message)

    def test_two_business_planes_read_same_landing(self) -> None:
        self.dedup.versioning.confirm_report(self.report["报告编号"])
        self.dedup.versioning.write_landing(
            {"报告编号": self.report["报告编号"], "存储配置编号": "STOR-0003"})
        dedup_rows = self.dedup.versioning.list_landing(report_code=self.report["报告编号"])
        storage_rows = self.storage.dedup_versioning.list_landing(
            report_code=self.report["报告编号"])
        self.assertEqual(len(dedup_rows), 12)
        self.assertEqual(dedup_rows, storage_rows)
        distribution = Counter(row["判定结果"] for row in dedup_rows)
        self.assertEqual(distribution["保留"], 7)
        self.assertEqual(distribution["重复"], 5)
        self.assertTrue(all(row["策略版本"] == self.report["策略版本"] for row in dedup_rows))


class JudgeEngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _, _, self.store = new_services()

    def test_threshold_tightens_duplicate_set(self) -> None:
        records = self.store.rows("dedup_records")
        loose = judge_records(records, threshold=0.8, algorithm="文本相似度", keep_order="最早采集优先")
        tight = judge_records(records, threshold=0.7, algorithm="文本相似度", keep_order="最早采集优先")
        self.assertGreaterEqual(len(tight["duplicates"]), len(loose["duplicates"]))
        self.assertLessEqual(len(tight["kept"]), len(loose["kept"]))

    def test_exact_match_algorithm(self) -> None:
        records = self.store.rows("dedup_records")
        result = judge_records(records, threshold=0.99, algorithm="精确匹配", keep_order="最早采集优先")
        # 精确匹配下没有任何预置内容完全相等的记录，全部保留。
        self.assertEqual(len(result["kept"]), len(records))


if __name__ == "__main__":
    unittest.main()
