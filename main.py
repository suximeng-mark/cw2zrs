"""
值日生插件
显示今日值日生，支持自定义分组并按周轮换。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from ClassWidgets.SDK import ConfigBaseModel, CW2Plugin, PluginAPI
from PySide6.QtCore import Signal, Slot


class DutyMember(ConfigBaseModel):
    """单个值日成员"""
    name: str = ""
    task: str = ""


class DutyGroup(ConfigBaseModel):
    """值日小组"""
    name: str = "第1组"
    members: List[DutyMember] = []


class DutyConfig(ConfigBaseModel):
    """值日生配置"""
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
    # 起始日期 (YYYY-MM-DD)
    start_date: str = "2025-09-01"
    # 轮换模式："weekly"=按周轮换，"daily"=每天轮换，"workday"=工作日轮换（周末仅算1日）
    rotation_mode: str = "weekly"
    # 手动切换偏移量（相对自动计算结果的偏移）
    manual_offset: int = 0


class Plugin(CW2Plugin):
    """值日生插件"""

    # 当日值日生数据变化时发射，Widget 监听此信号刷新
    dutyChanged = Signal()

    def __init__(self, api: PluginAPI) -> None:
        super().__init__(api)
        self.config = DutyConfig()

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def on_load(self) -> None:
        super().on_load()
        if self.pid is None:
            return

        # 注册配置模型
        self.api.config.register_plugin_model(self.pid, self.config)

        # 注册 Widget
        self.api.widgets.register(
            widget_id="com.classwidgets.duty-student.widget",
            name="今日值日生",
            qml_path="assets/widget.qml",
            backend_obj=self,
        )

        # 注册设置页
        self.api.ui.register_settings_page(
            qml_path="assets/settings.qml",
            title="值日生设置",
            icon="ic_fluent_people_20_regular",
        )

    def on_unload(self) -> None:
        super().on_unload()

    # ------------------------------------------------------------------ #
    # 日期 / 轮换计算
    # ------------------------------------------------------------------ #
    def _parse_date(self, date_str: str) -> date:
        """解析日期字符串，失败则返回今天"""
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return date.today()

    def _count_workday_slots(self, start: date, today: date) -> int:
        """工作日模式：计算从 start 到 today 的轮换步数。

        规则：
        - 周一至周五：每天算 1 步
        - 周六：算 1 步（周末开始）
        - 周日：算 0 步（与周六合并为 1 天）
        即周末（周六+周日）仅算 1 日。
        """
        if today <= start:
            return 0
        slots = 0
        cur = start
        while cur < today:
            cur += timedelta(days=1)
            wd = cur.weekday()  # 0=周一 ... 5=周六, 6=周日
            if wd <= 4:        # 周一至周五
                slots += 1
            elif wd == 5:      # 周六
                slots += 1
            # 周日：不额外计数（与周六合并）
        return slots

    def _get_auto_index(self) -> int:
        """根据起始日期与今天计算自动轮换到的组索引"""
        groups = self.config.groups
        if not groups:
            return 0
        start = self._parse_date(self.config.start_date)
        today = date.today()
        days = max(0, (today - start).days)

        mode = self.config.rotation_mode
        if mode == "daily":
            # 每天轮换
            return days % len(groups)
        elif mode == "workday":
            # 工作日轮换：周末仅算 1 日
            slots = self._count_workday_slots(start, today)
            return slots % len(groups)
        else:
            # 按周轮换（默认）：每周换一组
            weeks = days // 7
            return weeks % len(groups)

    def _get_period_number(self) -> int:
        """当前轮换周期序号，从 1 开始"""
        start = self._parse_date(self.config.start_date)
        today = date.today()
        days = max(0, (today - start).days)

        mode = self.config.rotation_mode
        if mode == "daily":
            return days + 1
        elif mode == "workday":
            return self._count_workday_slots(start, today) + 1
        else:
            return days // 7 + 1

    def _get_current_index(self) -> int:
        """当前实际显示的组索引（含手动偏移）"""
        groups = self.config.groups
        if not groups:
            return 0
        auto = self._get_auto_index()
        return (auto + self.config.manual_offset) % len(groups)

    # ------------------------------------------------------------------ #
    # 供 Widget 调用的方法
    # ------------------------------------------------------------------ #
    @Slot(result="QVariant")
    def get_today_duty(self) -> Dict[str, Any]:
        """返回今日值日生数据，供 Widget 展示"""
        groups = self.config.groups
        if not groups:
            return {
                "groupName": "未配置",
                "periodNumber": 0,
                "rotationMode": self.config.rotation_mode,
                "autoIndex": 0,
                "currentIndex": 0,
                "totalGroups": 0,
                "members": [],
                "date": date.today().isoformat(),
                "offset": self.config.manual_offset,
            }

        idx = self._get_current_index()
        auto_idx = self._get_auto_index()
        group = groups[idx]
        today = date.today()

        return {
            "groupName": group.name,
            "periodNumber": self._get_period_number(),
            "rotationMode": self.config.rotation_mode,
            "autoIndex": auto_idx,
            "currentIndex": idx,
            "totalGroups": len(groups),
            "members": [
                {"name": m.name, "task": m.task}
                for m in group.members
            ],
            "date": today.isoformat(),
            "offset": self.config.manual_offset,
        }

    @Slot(result="QVariant")
    def get_groups(self) -> List[Dict[str, Any]]:
        """返回所有分组配置，供设置页展示"""
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
        """一次性保存起始日期、轮换模式和分组配置。

        QML 端调用示例：
            backend.save_all(startDateText, rotationMode, JSON.stringify(groupsData))
        """
        import json
        from loguru import logger

        try:
            logger.info(f"[值日生] save_all 收到: mode={rotation_mode!r}, start={start_date!r}")
            # 解析分组数据
            if isinstance(data, (str, bytes, bytearray)):
                data = json.loads(data)
            else:
                try:
                    data = json.loads(json.dumps(data, default=lambda o: dict(o)))
                except TypeError:
                    pass

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
                groups.append(
                    DutyGroup(
                        name=str(g.get("name", "") or "未命名组"),
                        members=members,
                    )
                )

            mode = rotation_mode if rotation_mode in ("weekly", "daily", "workday") else "weekly"
            self.config.start_date = str(start_date or "")
            self.config.rotation_mode = mode
            self.config.groups = groups
            self.api.config.save()
            self.dutyChanged.emit()
            logger.info(
                f"[值日生] 保存成功：{len(groups)} 组, 模式={mode}, 起始日期={self.config.start_date}"
            )
        except Exception as e:
            logger.error(f"[值日生] 保存失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    @Slot("QVariant")
    def save_groups(self, data: Any) -> None:
        """仅保存分组（兼容旧调用，建议改用 save_all）。"""
        self.save_all(self.config.start_date, self.config.rotation_mode, data)

    @Slot(result=str)
    def get_start_date(self) -> str:
        return self.config.start_date

    @Slot(result=str)
    def get_rotation_mode(self) -> str:
        return self.config.rotation_mode

    @Slot(str)
    def set_rotation_mode(self, mode: str) -> None:
        if mode in ("weekly", "daily", "workday"):
            self.config.rotation_mode = mode
            self.api.config.save()
            self.dutyChanged.emit()

    @Slot(str)
    def set_start_date(self, date_str: str) -> None:
        self.config.start_date = date_str
        self.api.config.save()
        self.dutyChanged.emit()

    @Slot(result=int)
    def get_manual_offset(self) -> int:
        return self.config.manual_offset

    @Slot()
    def prev_group(self) -> None:
        """切换到上一组"""
        if not self.config.groups:
            return
        self.config.manual_offset -= 1
        self.api.config.save()
        self.dutyChanged.emit()

    @Slot()
    def next_group(self) -> None:
        """切换到下一组"""
        if not self.config.groups:
            return
        self.config.manual_offset += 1
        self.api.config.save()
        self.dutyChanged.emit()

    @Slot()
    def reset_group(self) -> None:
        """重置为自动计算的组"""
        self.config.manual_offset = 0
        self.api.config.save()
        self.dutyChanged.emit()
