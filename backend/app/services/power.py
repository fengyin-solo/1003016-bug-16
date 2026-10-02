"""动力配套业务规则：状态流转、字段校验与筛选口径都收在这里。

检修链路约定：
- 设备状态只能按「正常运行 → 降额运行 → 故障停机 → 已报废」单向流转，不允许回退；
- 已报废设备不能再排检修；要复用必须先把检修流程补完（完成检修并登记检修日期）；
- 检修日期（上次检修、下次检修日）留空会被拦下，并说明缺哪一项；
- 列表与详情走同一份序列化口径，保证下次检修日等字段两边一致。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "power"
REQUIRED_FIELDS = ["设备编号", "设备类型", "额定功率"]
MAINTENANCE_FIELDS = ["上次检修", "下次检修日"]
STATUS_ORDER = ["正常运行", "降额运行", "故障停机", "已报废"]
SCRAPPED = STATUS_ORDER[-1]
ACTION_RULES = {"降额运行": "降额运行", "故障停机": "故障停机", "申请报废": "已报废"}
COMPLETE_ACTION = "完成检修"


class PowerService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 按 id 稳定排序，翻页时记录不会错位、缺段
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设备编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._serialize(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._serialize(entry), []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        """排检修：登记检修日期。已报废的设备不能再排，日期留空要说明缺哪项。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [], f"电源设备 {entry_id} 不存在或已归档"
        if entry.get("status") == SCRAPPED:
            return None, [], "设备已报废，不能再排检修；如需复用请先完成检修"
        missing = [field for field in MAINTENANCE_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        for field in MAINTENANCE_FIELDS:
            entry[field] = str(values.get(field)).strip()
        return self._serialize(entry), [], "检修日期已保存"

    def run_action(self, entry_id: int, action: str, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电源设备 {entry_id} 不存在或已归档"
        if action == COMPLETE_ACTION:
            return self._complete_maintenance(entry, values or {})
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于动力配套可执行范围"
        current = str(entry.get("status") or STATUS_ORDER[0])
        if current == SCRAPPED:
            return None, "设备已报废，不能再排检修；如需复用请先完成检修"
        target = ACTION_RULES[action]
        if STATUS_ORDER.index(target) <= STATUS_ORDER.index(current):
            order = " → ".join(STATUS_ORDER)
            return None, f"设备状态只能按「{order}」单向流转，不能从「{current}」切到「{target}」"
        entry["status"] = target
        entry["pending"] = target != SCRAPPED
        entry["abnormal"] = target in STATUS_ORDER[1:-1]
        return self._serialize(entry), f"电源设备已{action}"

    def _complete_maintenance(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """完成检修：登记检修日期；已报废设备借此补完检修流程、恢复正常运行。"""
        missing = [field for field in MAINTENANCE_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"完成检修被拦下，缺少：{'、'.join(missing)}"
        for field in MAINTENANCE_FIELDS:
            entry[field] = str(values.get(field)).strip()
        if entry.get("status") == SCRAPPED:
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            return self._serialize(entry), "检修流程已补完，设备恢复正常运行"
        return self._serialize(entry), "电源设备检修完成，检修日期已更新"

    def _serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        """列表与详情共用的输出口径：设备状态以流转状态为准。"""
        data = dict(row)
        data["设备状态"] = str(row.get("status") or STATUS_ORDER[0])
        return data
