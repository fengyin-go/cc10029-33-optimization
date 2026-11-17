"""重复去重接口：维护去重策略，覆盖提交校验、启用配置、停用配置等动作。

新增的阈值重算能力全部挂在 /api/dedup 下且为增量路由，既有列表、导出、
详情、登记、动作接口的字段名与返回结构保持稳定不变。
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import (
    ActionPayload,
    ActionResult,
    LandingPayload,
    PageResult,
    RecomputePayload,
    SetCurrentVersionPayload,
)
from app.services.dedup import DedupService

router = APIRouter(prefix="/api/dedup", tags=["重复去重"])

service = DedupService()

LIST_FIELDS = ["策略编号", "业务键列", "去重算法", "对比窗口", "相似阈值", "保留顺序", "增量模式", "生效批次"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按策略编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、策略编号关键字与状态过滤重复去重列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dedup.csv"'})


# ------------------------------------------------------------------
# 阈值重算：去重策略数据报告、去重版本、数据来源调用链
# ------------------------------------------------------------------
@router.post("/recompute", response_model=ActionResult, status_code=201)
def recompute(strategy_code: str = Query(..., description="去重策略编号，如 DEDU-0003"),
              payload: RecomputePayload | None = None) -> ActionResult:
    """按新阈值与重新判定范围重新判定，生成去重策略数据报告与新的去重版本。

    并发写入只允许一个提交成功；同一幂等键重复提交只生效一次。
    """
    strategy = service.get_strategy_by_code(strategy_code)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"去重策略 {strategy_code} 不存在或已归档")
    values = payload.model_dump() if payload is not None else {}
    report, message, code = service.versioning.submit_report(strategy, values)
    if report is None:
        if code == 409:
            raise HTTPException(status_code=409, detail=message)
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=report)


@router.get("/reports", response_model=PageResult[dict])
def list_reports(
    strategy_code: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """列出去重策略数据报告，可按策略编号过滤；报告含旧阈值、新阈值与重新判定范围。"""
    rows = service.versioning.list_reports(strategy_code)
    total = len(rows)
    start = (page - 1) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("/reports/{report_code}", response_model=dict)
def get_report(report_code: str) -> dict:
    """读取单份报告的完整重算结果，含新旧保留记录、重复证据与口径冲突。"""
    report = service.versioning.find_report(report_code)
    if report is None:
        raise HTTPException(status_code=404, detail=f"去重策略数据报告 {report_code} 不存在")
    return report


@router.post("/reports/{report_code}/confirm", response_model=ActionResult)
def confirm_report(report_code: str) -> ActionResult:
    """确认报告中的策略版本，确认后才允许存储落地。"""
    report, message = service.versioning.confirm_report(report_code)
    if report is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=report)


@router.get("/versions", response_model=PageResult[dict])
def list_versions(strategy_code: str | None = Query(default=None)) -> PageResult[dict]:
    """列出去重版本：冻结版与最新版，同一策略始终只有一个当前版本。"""
    rows = service.versioning.list_versions(strategy_code)
    return PageResult(items=rows, total=len(rows), page=1, size=len(rows) or 1)


@router.post("/versions/current", response_model=ActionResult)
def set_current_version(strategy_code: str = Query(...),
                        payload: SetCurrentVersionPayload | None = None) -> ActionResult:
    """在冻结版或最新版之间取舍，切换重复去重当前版本。"""
    if payload is None or not payload.策略版本.strip():
        return ActionResult(ok=False, message="策略版本不能为空")
    version, message = service.versioning.set_current_version(strategy_code, payload.策略版本.strip())
    if version is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=version)


@router.get("/trace-source")
def trace_source(strategy_code: str = Query(...), report_code: str | None = Query(default=None)) -> dict:
    """沿着重复去重调用链定位去重策略数据报告的数据来源。"""
    if service.get_strategy_by_code(strategy_code) is None:
        raise HTTPException(status_code=404, detail=f"去重策略 {strategy_code} 不存在或已归档")
    return service.versioning.trace_source(strategy_code, report_code)


# ------------------------------------------------------------------
# 去重落地清单（回写到存储落地业务面，读取入口同样在存储落地路由暴露）
# ------------------------------------------------------------------
@router.get("/landing")
def list_landing(
    report_code: str | None = Query(default=None),
    storage_code: str | None = Query(default=None),
    strategy_code: str | None = Query(default=None),
    current_only: bool = Query(default=False),
) -> dict:
    """读取去重落地清单；默认只返回标记为当前版本的记录。"""
    rows = service.versioning.list_landing(
        report_code=report_code, storage_code=storage_code,
        strategy_code=strategy_code, current_only=current_only)
    return {"items": rows, "total": len(rows), "page": 1, "size": len(rows) or 1}


@router.post("/landing", response_model=ActionResult, status_code=201)
def create_landing(payload: LandingPayload) -> ActionResult:
    """存储落地读取已确认报告生成去重落地清单，版本不一致或重复落地一律拒绝。"""
    summary, message, code = service.versioning.write_landing(payload.model_dump())
    if summary is None:
        if code in (404, 409):
            raise HTTPException(status_code=code, detail=message)
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=summary)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条去重策略明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"去重策略 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条去重策略，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="去重策略已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条去重策略执行提交校验、启用配置、停用配置；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
