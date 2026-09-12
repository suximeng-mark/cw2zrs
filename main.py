from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from ClassWidgets.SDK import ConfigBaseModel, CW2Plugin, PluginAPI
from PySide6.QtCore import QTimer, Signal, Slot

MODE_WEEKLY = "weekly"
MODE_DAILY = "daily"
MODE_WORKDAY = "workday"
VALID_MODES = (MODE_WEEKLY, MODE_DAILY, MODE_WORKDAY)


class DutyMember(ConfigBaseModel):
    name: str = ""
    task: str = ""


class DutyGroup(ConfigBaseModel):
    name: str = "第1组"
    members: List[DutyMember] = []


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
            widget_id="com.classwidgets.duty-student.widget",
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

    def _parse_date(self, date_str: str) -> date:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return date.today()

    def _elapsed_slots(self, today: date | None = None) -> int:
        start = self._parse_date(self.config.start_date)
        today = today or date.today()
        days = max(0, (today - start).days)

        mode = self.config.rotation_mode
        if mode == MODE_DAILY:
            return days
        if mode == MODE_WEEKLY:
            return days // 7

        full_weeks, remainder = divmod(days, 7)
        slots = full_weeks * 6
        for k in range(1, remainder + 1):
            if (start + timedelta(days=k)).weekday() != 6:
                slots += 1
        return slots

    def _current_index(self) -> int:
        groups = self.config.groups
        if not groups:
            return 0
        return (self._elapsed_slots() + self.config.manual_offset) % len(groups)

    def _persist(self) -> None:
        self.api.config.save()
        QTimer.singleShot(0, self.dutyChanged.emit)

    @Slot(result="QVariant")
    def get_today_duty(self) -> Dict[str, Any]:
        today = date.today()
        groups = self.config.groups

        result: Dict[str, Any] = {
            "rotationMode": self.config.rotation_mode,
            "periodNumber": self._elapsed_slots(today) + 1,
            "totalGroups": len(groups),
            "autoIndex": self._elapsed_slots(today) % len(groups) if groups else 0,
            "currentIndex": 0,
            "groupName": "未配置",
            "members": [],
            "date": today.isoformat(),
            "offset": self.config.manual_offset,
        }

        if groups:
            idx = self._current_index()
            group = groups[idx]
            result.update({
                "currentIndex": idx,
                "groupName": group.name,
                "members": [
                    {"name": m.name, "task": m.task}
                    for m in group.members
                ],
            })
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
