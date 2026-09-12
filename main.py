from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from ClassWidgets.SDK import ConfigBaseModel, CW2Plugin, PluginAPI
from PySide6.QtCore import QTimer, Signal, Slot

MODE_WEEKLY = "weekly"
MODE_DAILY = "daily"
MODE_WORKDAY = "workday"
VALID_MODES = (MODE_WEEKLY, MODE_DAILY, MODE_WORKDAY)

STATUS_NORMAL = "normal"
STATUS_ABSENT = "absent"

HISTORY_LIMIT = 400


class DutyMember(ConfigBaseModel):
    name: str = ""
    task: str = ""


class DutyGroup(ConfigBaseModel):
    name: str = "第1组"
    members: List[DutyMember] = []


class Holiday(ConfigBaseModel):
    start: str = ""
    end: str = ""
    name: str = ""


class DutyMemberStatus(ConfigBaseModel):
    name: str = ""
    task: str = ""
    status: str = STATUS_NORMAL


class DutyRecord(ConfigBaseModel):
    date: str = ""
    group_name: str = ""
    auto_group_name: str = ""
    members: List[DutyMemberStatus] = []


class DutyConfig(ConfigBaseModel):
    groups: List[DutyGroup] = [
        DutyGroup(
            name="第1组",
            members=[
                DutyMember(name="张三", task="扫地"),
                DutyMember(name="李四", task="擦黑板"),
                DutyMember(name="王五", task="倒垃圾"),
            ],
        ),
        DutyGroup(
            name="第2组",
            members=[
                DutyMember(name="赵六", task="扫地"),
                DutyMember(name="钱七", task="擦黑板"),
                DutyMember(name="孙八", task="倒垃圾"),
            ],
        ),
    ]
    start_date: str = "2025-09-01"
    rotation_mode: str = MODE_WEEKLY
    manual_offset: int = 0
    holidays: List[Holiday] = []
    history: List[DutyRecord] = []


class Plugin(CW2Plugin):
    dutyChanged = Signal()

    def __init__(self, api: PluginAPI) -> None:
        super().__init__(api)
        self.config = DutyConfig()

    def on_load(self) -> None:
        super().on_load()
        if self.pid is None:
            return

        self.api.config.register_plugin_model(self.pid, self.config)

        self.api.widgets.register(
            widget_id="com.studentondutyshow.com.widget",
            name="今日值日生",
            qml_path="assets/widget.qml",
            backend_obj=self,
        )

        self.api.ui.register_settings_page(
            qml_path="assets/settings.qml",
            title="值日生设置",
            icon="ic_fluent_people_20_regular",
        )

    def on_unload(self) -> None:
        super().on_unload()

    # ------------------------------------------------------------------ utils
    def _parse_date(self, date_str: str) -> date:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return date.today()

    def _is_holiday(self, day: date) -> bool:
        iso = day.isoformat()
        for h in self.config.holidays:
            if h.start and h.start <= iso <= (h.end or h.start):
                return True
        return False

    def _holiday_name(self, day: date) -> str:
        iso = day.isoformat()
        for h in self.config.holidays:
            if h.start and h.start <= iso <= (h.end or h.start):
                return h.name or "假期"
        return ""

    def _elapsed_slots(self, today: Optional[date] = None) -> int:
        """从起始日期到 today（不含首日）经历的轮换次数；假期不推进轮换。

        - daily：每个非假期自然日 +1
        - workday：每个非假期工作日 +1；周末（六日）整体最多 +1
        - weekly：以起始日为锚点每 7 天为一周，整周都是假期才跳过
        """
        start = self._parse_date(self.config.start_date)
        today = today or date.today()
        if today <= start:
            return 0

        mode = self.config.rotation_mode
        days = (today - start).days

        if mode == MODE_DAILY:
            return sum(
                1
                for k in range(1, days + 1)
                if not self._is_holiday(start + timedelta(days=k))
            )

        if mode == MODE_WEEKLY:
            slots = 0
            block_start = start + timedelta(days=7)
            while block_start <= today:
                block_days = (block_start + timedelta(days=n) for n in range(7))
                if any(not self._is_holiday(d) for d in block_days):
                    slots += 1
                block_start += timedelta(days=7)
            return slots

        # workday
        slots = 0
        cur = start + timedelta(days=1)
        while cur <= today:
            wd = cur.weekday()
            if wd < 5:  # 周一至周五
                if not self._is_holiday(cur):
                    slots += 1
            elif wd == 5:  # 周六：与周日合并为一个周末档
                sunday = cur + timedelta(days=1)
                if not self._is_holiday(cur) or (
                    sunday <= today and not self._is_holiday(sunday)
                ):
                    slots += 1
            else:  # 周日：仅当周六早于起始日（起始日即周日）时单独计档
                saturday = cur - timedelta(days=1)
                if saturday < start and not self._is_holiday(cur):
                    slots += 1
            cur += timedelta(days=1)
        return slots

    def _current_index(self) -> int:
        groups = self.config.groups
        if not groups:
            return 0
        return (self._elapsed_slots() + self.config.manual_offset) % len(groups)

    def _persist(self) -> None:
        self.api.config.save()
        QTimer.singleShot(0, self.dutyChanged.emit)

    # -------------------------------------------------------------- history
    def _snapshot_today(
        self, today: date, idx: int, auto_idx: int, group: DutyGroup
    ) -> None:
        """把今日值日快照写入历史（一天一条；手动换组后重置当日考勤）。"""
        iso = today.isoformat()
        history = list(self.config.history)
        record = next((r for r in history if r.date == iso), None)

        auto_name = ""
        if self.config.groups:
            auto_name = self.config.groups[auto_idx].name

        if record is None:
            history.append(DutyRecord(
                date=iso,
                group_name=group.name,
                auto_group_name=auto_name,
                members=[
                    DutyMemberStatus(name=m.name, task=m.task, status=STATUS_NORMAL)
                    for m in group.members
                ],
            ))
            changed = True
        else:
            changed = False
            if record.group_name != group.name:
                record.group_name = group.name
                record.members = [
                    DutyMemberStatus(name=m.name, task=m.task, status=STATUS_NORMAL)
                    for m in group.members
                ]
                changed = True
            if record.auto_group_name != auto_name:
                record.auto_group_name = auto_name
                changed = True

        if changed:
            history.sort(key=lambda r: r.date)
            if len(history) > HISTORY_LIMIT:
                history = history[-HISTORY_LIMIT:]
            self.config.history = history
            # 读路径上的自动快照只落盘，不发信号，避免与前端刷新形成回路
            self.api.config.save()

    # ---------------------------------------------------------------- slots
    @Slot(result="QVariant")
    def get_today_duty(self) -> Dict[str, Any]:
        today = date.today()
        groups = self.config.groups
        slots = self._elapsed_slots(today)
        auto_idx = slots % len(groups) if groups else 0

        result: Dict[str, Any] = {
            "rotationMode": self.config.rotation_mode,
            "periodNumber": slots + 1,
            "totalGroups": len(groups),
            "autoIndex": auto_idx,
            "currentIndex": 0,
            "groupName": "未配置",
            "members": [],
            "date": today.isoformat(),
            "offset": self.config.manual_offset,
            "switched": False,
            "isHoliday": self._is_holiday(today),
            "holidayName": self._holiday_name(today),
        }

        if groups:
            idx = (slots + self.config.manual_offset) % len(groups)
            group = groups[idx]
            statuses: List[str] = []
            iso = today.isoformat()
            rec = next(
                (r for r in self.config.history if r.date == iso), None
            )
            if rec is not None and rec.group_name == group.name:
                statuses = [m.status for m in rec.members]
            result.update({
                "currentIndex": idx,
                "groupName": group.name,
                "switched": idx != auto_idx,
                "members": [
                    {
                        "name": m.name,
                        "task": m.task,
                        "status": statuses[i] if i < len(statuses) else STATUS_NORMAL,
                    }
                    for i, m in enumerate(group.members)
                ],
            })
            self._snapshot_today(today, idx, auto_idx, group)
        return result

    @Slot(result="QVariant")
    def get_groups(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": g.name,
                "members": [
                    {"name": m.name, "task": m.task}
                    for m in g.members
                ],
            }
            for g in self.config.groups
        ]

    @Slot(str, str, "QVariant")
    def save_all(self, start_date: str, rotation_mode: str, data: Any) -> None:
        import json
        from loguru import logger

        try:
            if isinstance(data, (str, bytes, bytearray)):
                data = json.loads(data)
            else:
                def _to_serializable(o):
                    if isinstance(o, dict):
                        return {k: _to_serializable(v) for k, v in o.items()}
                    if isinstance(o, (list, tuple)):
                        return [_to_serializable(i) for i in o]
                    if hasattr(o, "__dict__"):
                        return _to_serializable(vars(o))
                    return str(o)
                data = json.loads(json.dumps(data, default=_to_serializable))

            if not isinstance(data, list):
                raise ValueError(f"groups data must be a list, got {type(data)}")

            groups: List[DutyGroup] = []
            for g in data:
                if not isinstance(g, dict):
                    raise ValueError(f"group must be a dict, got {type(g)}")
                members = [
                    DutyMember(
                        name=str(m.get("name", "") or ""),
                        task=str(m.get("task", "") or ""),
                    )
                    for m in (g.get("members", []) or [])
                ]
                groups.append(DutyGroup(
                    name=str(g.get("name", "") or "未命名组"),
                    members=members,
                ))

            self.config.start_date = str(start_date or "")
            self.config.rotation_mode = rotation_mode if rotation_mode in VALID_MODES else MODE_WEEKLY
            self.config.groups = groups
            logger.info(
                f"[值日生] 保存成功：{len(groups)} 组, 模式={self.config.rotation_mode}, "
                f"起始日期={self.config.start_date}"
            )
            self._persist()
        except Exception as e:
            logger.error(f"[值日生] 保存失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    @Slot(result=str)
    def get_start_date(self) -> str:
        return self.config.start_date

    @Slot(result=str)
    def get_rotation_mode(self) -> str:
        return self.config.rotation_mode

    @Slot()
    def prev_group(self) -> None:
        if self.config.groups:
            self.config.manual_offset -= 1
            self._persist()

    @Slot()
    def next_group(self) -> None:
        if self.config.groups:
            self.config.manual_offset += 1
            self._persist()

    @Slot()
    def reset_group(self) -> None:
        self.config.manual_offset = 0
        self._persist()

    # -------------------------------------------------------------- holidays
    @Slot(result="QVariant")
    def get_holidays(self) -> List[Dict[str, Any]]:
        return [
            {"start": h.start, "end": h.end or h.start, "name": h.name}
            for h in self.config.holidays
        ]

    @Slot("QVariant", result=bool)
    def save_holidays(self, data: Any) -> bool:
        import json
        from loguru import logger

        try:
            if isinstance(data, (str, bytes, bytearray)):
                data = json.loads(data)
            if not isinstance(data, list):
                raise ValueError(f"holidays must be a list, got {type(data)}")

            def _strict_parse(value: Any) -> Optional[date]:
                try:
                    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    return None

            normalized: List[Holiday] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                start = _strict_parse(item.get("start", ""))
                if start is None:
                    continue
                end_raw = str(item.get("end", "") or "").strip()
                end = _strict_parse(end_raw) if end_raw else start
                if end is None:
                    continue
                if end < start:
                    start, end = end, start
                name = str(item.get("name", "") or "").strip()
                normalized.append(Holiday(
                    start=start.isoformat(),
                    end=end.isoformat(),
                    name=name,
                ))

            normalized.sort(key=lambda h: h.start)
            self.config.holidays = normalized
            logger.info(f"[值日生] 假期已保存：{len(normalized)} 个时间段")
            self._persist()
            return True
        except Exception as e:
            logger.error(f"[值日生] 假期保存失败: {e}")
            return False

    # --------------------------------------------------------- attendance
    @Slot(str, int, str, result=bool)
    def set_member_status(self, day: str, member_index: int, status: str) -> bool:
        from loguru import logger

        if status not in (STATUS_NORMAL, STATUS_ABSENT):
            return False
        record = next((r for r in self.config.history if r.date == day), None)
        if record is None or not (0 <= member_index < len(record.members)):
            return False
        record.members[member_index].status = status
        logger.info(
            f"[值日生] 考勤已记录：{day} {record.members[member_index].name} -> {status}"
        )
        self._persist()
        return True

    @Slot(result="QVariant")
    def get_stats(self) -> Dict[str, Any]:
        per_person: Dict[str, Dict[str, Any]] = {}
        recent: List[Dict[str, Any]] = []

        records = sorted(self.config.history, key=lambda r: r.date)
        for r in records:
            seen = set()
            switched = bool(r.auto_group_name) and r.group_name != r.auto_group_name
            members_out = []
            for m in r.members:
                members_out.append({"name": m.name, "task": m.task, "status": m.status})
                if not m.name or m.name in seen:
                    continue
                seen.add(m.name)
                entry = per_person.setdefault(m.name, {
                    "name": m.name, "count": 0, "absent": 0,
                })
                entry["count"] += 1
                if m.status == STATUS_ABSENT:
                    entry["absent"] += 1
            recent.append({
                "date": r.date,
                "groupName": r.group_name,
                "switched": switched,
                "members": members_out,
            })

        rows = sorted(
            per_person.values(),
            key=lambda e: (-e["count"], e["name"]),
        )
        return {
            "days": len(records),
            "rows": rows,
            "recent": recent[-15:][::-1],
        }

    @Slot()
    def clear_history(self) -> None:
        from loguru import logger

        self.config.history = []
        logger.info("[值日生] 历史记录已清空")
        self._persist()
