"""动力配套接口：维护电源设备，覆盖降额运行、故障停机、申请报废与检修安排。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.power import (
    NEXT_MAINT_DATE,
    PowerService,
)

router = APIRouter(prefix="/api/power", tags=["动力配套"])

service = PowerService()

LIST_FIELDS = [
    "设备编号", "设备类型", "额定功率", "所属站点", "投用日期",
    "上次检修", NEXT_MAINT_DATE, "检修状态", "设备状态",
]
STATUSES = ["正常运行", "降额运行", "故障停机", "已报废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按设备编号检索"),
    status: str | None = Query(default=None, description="正常运行、降额运行、故障停机、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按设备编号与状态过滤动力配套列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 注意：静态路径必须注册在 /{entry_id} 之前，否则 export 会被当成设备 id
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出动力配套清单：返回全量数据（列表与详情同源，口径一致）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "power", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条电源设备明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"电源设备 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条电源设备，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="电源设备已登记", entry=entry)


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改设备字段（如已排检修计划的下次检修日）；空日期会被拦下并指出缺哪项。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条电源设备执行降额运行、故障停机、申请报废；只能按状态次序顺次推进。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/maintenance", response_model=ActionResult)
def run_maintenance(entry_id: int, payload: EntryPayload) -> ActionResult:
    """检修链路：排检修（下次检修日必填，报废设备拦下）或完成检修（补完流程后复用）。"""
    action = str(payload.values.get("action") or "").strip()
    if action == "安排检修":
        entry, message = service.schedule_maintenance(
            entry_id, payload.values.get(NEXT_MAINT_DATE)
        )
    elif action == "完成检修":
        entry, message = service.complete_maintenance(entry_id)
    else:
        entry, message = None, f"检修动作「{action}」不支持，请使用安排检修或完成检修"
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
