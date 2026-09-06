"""
值日生插件
显示今日值日生，支持自定义分组并按周轮换。
"""
from __future__ import annotations

from datetime import date, datetime
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
    # 起始日期 (YYYY-MM-DD)，该周为第 1 周
    start_date: str = "2025-09-01"
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

    def _get_auto_index(self) -> int:
        """根据起始日期与今天计算自动轮换到的组索引"""
        groups = self.config.groups
        if not groups:
            return 0
        start = self._parse_date(self.config.start_date)
        today = date.today()
        days = (today - start).days
        weeks = max(0, days // 7)
        return weeks % len(groups)

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
                "weekNumber": 0,
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
        start = self._parse_date(self.config.start_date)
        weeks = max(0, (today - start).days // 7) + 1

        return {
            "groupName": group.name,
            "weekNumber": weeks,
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

    @Slot("QVariant")
    def save_groups(self, data: Any) -> None:
        """保存分组配置（QML 直接传入 JS 数组对象）"""
        try:
            if isinstance(data, str):
                import json
                data = json.loads(data)
            if not isinstance(data, list):
                raise ValueError("groups data must be a list")

            groups: List[DutyGroup] = []
            for g in data:
                members = [
                    DutyMember(
                        name=str(m.get("name", "") or ""),
                        task=str(m.get("task", "") or ""),
                    )
                    for m in (g.get("members", []) or [])
                ]
                groups.append(DutyGroup(name=str(g.get("name", "") or "未命名组"), members=members))
            self.config.groups = groups
            self.api.config.save()
            self.dutyChanged.emit()
        except Exception as e:
            print(f"[值日生] 保存分组失败: {e}")

    @Slot(result=str)
    def get_start_date(self) -> str:
        return self.config.start_date

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
