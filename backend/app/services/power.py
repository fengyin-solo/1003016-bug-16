"""动力配套业务规则：检修链路、状态流转、字段校验与筛选口径都收在这里。

状态只能沿「正常运行 → 降额运行 → 故障停机 → 已报废」顺次单向推进，
降额运行和故障停机之间不允许来回切。报废后唯一的复用出口是把既有检修
流程补完（完成检修后回到正常运行），且已报废设备不允许再新排检修。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "power"
REQUIRED_FIELDS = ["设备编号", "设备类型", "额定功率"]
STATUS_ORDER = ["正常运行", "降额运行", "故障停机", "已报废"]
ACTION_RULES = {"降额运行": "降额运行", "故障停机": "故障停机", "申请报废": "已报废"}
NEGATIVE_ACTIONS = ["降额运行", "故障停机"]

# 检修链路相关字段：列表和详情共用同一份，避免两处口径不一致
NEXT_MAINT_DATE = "下次检修日"
PREV_MAINT_DATE = "上次检修"
MAINT_PLAN_STATUS = "检修状态"
DISPLAY_STATUS = "设备状态"
PLAN_PENDING = "待检修"
PLAN_IDLE = "未安排"
SCRAPPED = STATUS_ORDER[-1]

# 允许通过编辑接口落库的字段，防止状态等被越权改写
EDITABLE_FIELDS = ["设备类型", "额定功率", "所属站点", "投用日期", PREV_MAINT_DATE, NEXT_MAINT_DATE]


def _sync_flags(entry: dict[str, Any]) -> None:
    """把派生字段同步成与状态、检修计划一致：设备状态展示列与异常/待处理标记。"""
    status = entry["status"]
    entry[DISPLAY_STATUS] = status
    entry["abnormal"] = status in ("降额运行", "故障停机")
    entry["pending"] = bool(entry["abnormal"]) or entry.get(MAINT_PLAN_STATUS) == PLAN_PENDING


class PowerService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设备编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry[MAINT_PLAN_STATUS] = PLAN_IDLE
        entry[NEXT_MAINT_DATE] = None
        entry[PREV_MAINT_DATE] = None
        _sync_flags(entry)
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """修改设备字段（如调整已排检修计划的下次检修日）；空日期直接拦下并说明缺哪项。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电源设备 {entry_id} 不存在或已归档"
        for field in EDITABLE_FIELDS:
            if field not in values:
                continue
            value = str(values.get(field) or "").strip()
            if field == NEXT_MAINT_DATE and not value:
                return None, f"缺少必填字段：{NEXT_MAINT_DATE}"
            entry[field] = value or None
        _sync_flags(entry)
        return entry, "检修安排已保存"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电源设备 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于动力配套可执行范围"
        target = ACTION_RULES[action]
        current_index = STATUS_ORDER.index(entry["status"])
        target_index = STATUS_ORDER.index(target)
        if target_index == current_index:
            return None, f"设备当前已是「{target}」，状态不能重复设置"
        if target_index < current_index:
            # 降额运行与故障停机之间来回切、报废后再回退都走这里拦下
            return None, (
                f"状态只能沿「{' → '.join(STATUS_ORDER)}」顺次推进，"
                f"当前为「{entry['status']}」，不能再{action}"
            )
        if target_index > current_index + 1:
            skipped = "、".join(STATUS_ORDER[current_index + 1:target_index])
            return None, f"需先依次经过「{skipped}」，才能{action}"
        entry["status"] = target
        _sync_flags(entry)
        return entry, f"电源设备已{action}"

    def schedule_maintenance(
        self, entry_id: int, next_date: Any
    ) -> tuple[dict[str, Any] | None, str]:
        """安排检修：日期必填；已报废设备一律不能再新排检修；已有待完成计划不重复排。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电源设备 {entry_id} 不存在或已归档"
        date = str(next_date or "").strip()
        if not date:
            return None, f"缺少必填字段：{NEXT_MAINT_DATE}"
        if entry["status"] == SCRAPPED:
            return None, "设备已报废，不能再排检修；如需复用，请先在详情里补完既有检修流程"
        if entry.get(MAINT_PLAN_STATUS) == PLAN_PENDING:
            return None, (
                f"已存在待完成的检修计划（{NEXT_MAINT_DATE}：{entry.get(NEXT_MAINT_DATE)}），"
                "请先完成本次检修后再重新排期"
            )
        entry[NEXT_MAINT_DATE] = date
        entry[MAINT_PLAN_STATUS] = PLAN_PENDING
        _sync_flags(entry)
        return entry, f"已安排 {date} 的检修计划"

    def complete_maintenance(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """完成检修：把检修流程补完是报废后复用的唯一出口，完成后设备回到正常运行。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电源设备 {entry_id} 不存在或已归档"
        if entry.get(MAINT_PLAN_STATUS) != PLAN_PENDING:
            return None, "没有待完成的检修计划，无需补完检修流程"
        finished_date = entry.get(NEXT_MAINT_DATE)
        if finished_date:
            entry[PREV_MAINT_DATE] = finished_date
        entry[NEXT_MAINT_DATE] = None
        entry[MAINT_PLAN_STATUS] = PLAN_IDLE
        entry["status"] = STATUS_ORDER[0]
        _sync_flags(entry)
        return entry, "检修流程已补完，设备恢复正常运行，可重新投入使用"
