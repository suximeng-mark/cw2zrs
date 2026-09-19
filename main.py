from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ClassWidgets.SDK import ConfigBaseModel, CW2Plugin, PluginAPI
from PySide6.QtCore import QTimer, Signal, Slot

MODE_WEEKLY = "weekly"
MODE_DAILY = "daily"
MODE_WORKDAY = "workday"
VALID_MODES = (MODE_WEEKLY, MODE_DAILY, MODE_WORKDAY)

STATUS_NORMAL = "normal"
STATUS_ABSENT = "absent"

HISTORY_LIMIT = 400
HISTORY_FLUSH_DELAY_MS = 1500
SLOTS_CACHE_LIMIT = 256

# 成员排列方式：inline=全部合并一行 / task=按岗位分行 / person=每人一行
LAYOUT_INLINE = "inline"
LAYOUT_TASK = "task"
LAYOUT_PERSON = "person"
VALID_LAYOUTS = (LAYOUT_INLINE, LAYOUT_TASK, LAYOUT_PERSON)

FONT_MIN = 9
FONT_MAX = 28

# 姓名与任务的配对样式：paren=姓名（任务）/ dot=姓名·任务 /
# columns=两列对齐 / taskfirst=任务：姓名
PAIR_PAREN = "paren"
PAIR_DOT = "dot"
PAIR_COLUMNS = "columns"
PAIR_TASKFIRST = "taskfirst"
VALID_PAIR_STYLES = (PAIR_PAREN, PAIR_DOT, PAIR_COLUMNS, PAIR_TASKFIRST)


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


# 注意：注册到 Class Widgets 的配置模型只保留体积小、变更频率低的字段。
# 历史考勤记录（history）持续增长且变化频繁，若放在注册模型中，每次变化都会
# 触发核心 configChanged，导致 QML 中所有 Configs.data 绑定各做一次全量
# model_dump（含全部插件配置），严重拖慢界面响应。因此 history 改用纯 dict
# 存放于插件独立的数据文件中，完全不进入 configs.json。
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
    # 显示设置：四个区域独立字号 + 普通模式成员排列方式
    font_group: int = 12   # 组名胶囊（底部按钮跟随）
    font_meta: int = 12    # 周期 / 假期 / 已调换徽标
    font_name: int = 14    # 成员姓名
    font_task: int = 14    # 任务
    member_layout: str = LAYOUT_TASK
    pair_style: str = PAIR_PAREN  # 姓名与任务的一一对应样式


class Plugin(CW2Plugin):
    dutyChanged = Signal()

    def __init__(self, api: PluginAPI) -> None:
        super().__init__(api)
        self.config = DutyConfig()
        # history 为纯 dict 列表：{date, group_name, auto_group_name,
        # members: [{name, task, status}]}
        self._history: List[Dict[str, Any]] = []
        self._history_path = Path(__file__).resolve().parent / "data" / "history.json"
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.timeout.connect(self._flush_history)
        # 显示设置（滑块拖动）防抖落盘
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.timeout.connect(self.api.config.save)
        # _elapsed_slots 结果缓存：fingerprint + 日期 -> 档位数
        self._slots_cache: Dict[tuple, int] = {}

    def on_load(self) -> None:
        super().on_load()
        if self.pid is None:
            return

        # 必须在 register_plugin_model 之前迁移：读取 configs.json 中
        # <=1.1.2 版本遗留在注册模型里的 history，搬入独立数据文件。
        had_legacy_history = self._migrate_legacy_history(self.pid)

        self.api.config.register_plugin_model(self.pid, self.config)

        if had_legacy_history:
            # 注册时核心已用新模型（不含 history）的 dump 覆盖内存中的插件配置，
            # 这里保存一次，让 configs.json 立即瘦身，避免核心下次退出时才落盘。
            try:
                self.api.config.save()
            except Exception:
                pass

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
        try:
            if self._display_timer.isActive():
                self._display_timer.stop()
                self.api.config.save()
            if self._history_timer.isActive():
                self._history_timer.stop()
                self._flush_history()
        finally:
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

        结果按 (起始日期, 模式, 假期, 目标日期) 缓存，同一天的重复调用为 O(1)。
        """
        start = self._parse_date(self.config.start_date)
        today = today or date.today()
        if today <= start:
            return 0

        fingerprint = (
            self.config.start_date,
            self.config.rotation_mode,
            tuple(
                sorted((h.start, h.end or h.start) for h in self.config.holidays)
            ),
            today.isoformat(),
        )
        cached = self._slots_cache.get(fingerprint, -1)
        if cached >= 0:
            return cached

        slots = self._compute_elapsed_slots(start, today)
        self._slots_cache[fingerprint] = slots
        if len(self._slots_cache) > SLOTS_CACHE_LIMIT:
            for old_key in list(self._slots_cache)[: SLOTS_CACHE_LIMIT // 2]:
                self._slots_cache.pop(old_key, None)
        return slots

    def _compute_elapsed_slots(self, start: date, today: date) -> int:
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

    @contextmanager
    def _batch_config_update(self) -> Iterator[None]:
        """临时挂起注册模型的变更回调，批量赋值结束后只触发一次
        model_dump 同步与 configChanged（否则每次 setattr 都会全量 dump）。"""
        cfg = self.config
        callback = getattr(cfg, "_on_change", None)
        cfg._on_change = None
        try:
            yield
        finally:
            cfg._on_change = callback
        if callback is not None:
            callback()

    def _persist(self) -> None:
        self.api.config.save()
        QTimer.singleShot(0, self.dutyChanged.emit)

    def _emit_duty_changed(self) -> None:
        QTimer.singleShot(0, self.dutyChanged.emit)

    def _display_payload(self) -> Dict[str, Any]:
        return {
            "fontGroup": self.config.font_group,
            "fontMeta": self.config.font_meta,
            "fontName": self.config.font_name,
            "fontTask": self.config.font_task,
            "memberLayout": self.config.member_layout,
            "pairStyle": self.config.pair_style,
        }

    # ------------------------------------------------- history (standalone)
    @staticmethod
    def _is_valid_record(item: Any) -> bool:
        return (
            isinstance(item, dict)
            and isinstance(item.get("date"), str)
            and isinstance(item.get("members"), list)
        )

    @staticmethod
    def _sanitize_record(item: Dict[str, Any]) -> Dict[str, Any]:
        members: List[Dict[str, str]] = []
        for m in item.get("members", []):
            if not isinstance(m, dict):
                continue
            status = m.get("status")
            if status not in (STATUS_NORMAL, STATUS_ABSENT):
                status = STATUS_NORMAL
            members.append({
                "name": str(m.get("name", "") or ""),
                "task": str(m.get("task", "") or ""),
                "status": status,
            })
        return {
            "date": str(item.get("date", "")),
            "group_name": str(item.get("group_name", "") or ""),
            "auto_group_name": str(item.get("auto_group_name", "") or ""),
            "members": members,
        }

    def _load_history_file(self) -> List[Dict[str, Any]]:
        try:
            with open(self._history_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (FileNotFoundError, OSError, ValueError):
            return []
        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return []
        return [
            self._sanitize_record(r)
            for r in records
            if self._is_valid_record(r)
        ]

    def _flush_history(self) -> None:
        """把 history 同步写入独立数据文件（原子替换）。"""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._history_path.with_name(self._history_path.name + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"records": self._history}, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._history_path)
        except Exception as e:
            try:
                from loguru import logger

                logger.warning(f"[值日生] 历史记录写入失败: {e}")
            except Exception:
                pass

    def _schedule_history_flush(self) -> None:
        self._history_timer.start(HISTORY_FLUSH_DELAY_MS)

    def _trim_history(self) -> None:
        if len(self._history) > HISTORY_LIMIT:
            self._history.sort(key=lambda r: r["date"])
            del self._history[: len(self._history) - HISTORY_LIMIT]

    def _migrate_legacy_history(self, plugin_id: str) -> bool:
        """从 configs.json 迁移 <=1.1.2 版本存放在注册模型中的 history。

        返回是否发现旧数据（调用方据此决定是否保存一次以瘦身 configs.json）。
        """
        self._history = self._load_history_file()

        legacy_raw: List[Any] = []
        try:
            # 生产环境：__file__ 位于 <CW根>/plugins/<plugin_id>/main.py
            configs_path = (
                Path(__file__).resolve().parents[2] / "configs" / "configs.json"
            )
            with open(configs_path, "r", encoding="utf-8") as f:
                root_cfg = json.load(f)
            plugin_cfgs = root_cfg.get("plugins", {}).get("configs", {})
            old_cfg = plugin_cfgs.get(plugin_id) if isinstance(plugin_cfgs, dict) else None
            if isinstance(old_cfg, dict) and isinstance(old_cfg.get("history"), list):
                legacy_raw = old_cfg["history"]
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            legacy_raw = []

        legacy = [
            self._sanitize_record(r)
            for r in legacy_raw
            if self._is_valid_record(r)
        ]
        if not legacy:
            return False

        # 独立文件中的记录优先，旧 configs 数据按日期补全
        merged: Dict[str, Dict[str, Any]] = {r["date"]: r for r in legacy}
        for r in self._history:
            merged[r["date"]] = r
        self._history = sorted(merged.values(), key=lambda r: r["date"])
        self._trim_history()
        self._flush_history()
        return True

    def _ensure_today_record(
        self, today: date, idx: int, auto_idx: int, group: DutyGroup
    ) -> Dict[str, Any]:
        """确保今日快照存在（纯内存操作，变更时防抖写入独立文件）。

        一天一条；手动换组后当日记录组名变化时重置考勤。
        不触碰注册模型、不写 configs.json、不触发 configChanged。
        """
        iso = today.isoformat()
        record = next((r for r in self._history if r["date"] == iso), None)
        auto_name = (
            self.config.groups[auto_idx].name if self.config.groups else ""
        )

        if record is None:
            record = {
                "date": iso,
                "group_name": group.name,
                "auto_group_name": auto_name,
                "members": [
                    {"name": m.name, "task": m.task, "status": STATUS_NORMAL}
                    for m in group.members
                ],
            }
            self._history.append(record)
            self._trim_history()
            self._schedule_history_flush()
            return record

        changed = False
        if record["group_name"] != group.name:
            record["group_name"] = group.name
            record["members"] = [
                {"name": m.name, "task": m.task, "status": STATUS_NORMAL}
                for m in group.members
            ]
            changed = True
        if record["auto_group_name"] != auto_name:
            record["auto_group_name"] = auto_name
            changed = True
        if changed:
            self._schedule_history_flush()
        return record

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
        result.update(self._display_payload())

        if groups:
            idx = (slots + self.config.manual_offset) % len(groups)
            group = groups[idx]
            # 纯内存 + 独立文件防抖写；不调用 config.save()，不触发 configChanged
            record = self._ensure_today_record(today, idx, auto_idx, group)
            statuses = (
                [m["status"] for m in record["members"]]
                if record["group_name"] == group.name
                else []
            )
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

            with self._batch_config_update():
                self.config.start_date = str(start_date or "")
                self.config.rotation_mode = (
                    rotation_mode if rotation_mode in VALID_MODES else MODE_WEEKLY
                )
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

    # --------------------------------------------------------- display
    @Slot(result="QVariant")
    def get_display_settings(self) -> Dict[str, Any]:
        return self._display_payload()

    @Slot(int, int, int, int, str, str, result=bool)
    def save_display_settings(
        self,
        font_group: int,
        font_meta: int,
        font_name: int,
        font_task: int,
        member_layout: str,
        pair_style: str,
    ) -> bool:
        """保存显示设置。滑块拖动时高频调用：setattr 只触发一次
        configChanged（实时预览），写盘防抖 400ms 合并。"""
        from loguru import logger

        try:
            def clamp(v: Any) -> int:
                v = int(v)
                return max(FONT_MIN, min(FONT_MAX, v))

            layout = member_layout if member_layout in VALID_LAYOUTS else LAYOUT_TASK
            pair = pair_style if pair_style in VALID_PAIR_STYLES else PAIR_PAREN
            with self._batch_config_update():
                self.config.font_group = clamp(font_group)
                self.config.font_meta = clamp(font_meta)
                self.config.font_name = clamp(font_name)
                self.config.font_task = clamp(font_task)
                self.config.member_layout = layout
                self.config.pair_style = pair
            self._emit_duty_changed()
            self._display_timer.start(400)
            return True
        except (ValueError, TypeError) as e:
            logger.error(f"[值日生] 显示设置保存失败: {e}")
            return False

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
        record = next((r for r in self._history if r["date"] == day), None)
        if record is None or not (0 <= member_index < len(record["members"])):
            return False
        record["members"][member_index]["status"] = status
        logger.info(
            f"[值日生] 考勤已记录：{day} "
            f"{record['members'][member_index]['name']} -> {status}"
        )
        # 只写独立 history 文件，不触发 configs.json 全量保存
        self._schedule_history_flush()
        self._emit_duty_changed()
        return True

    @Slot(result="QVariant")
    def get_stats(self) -> Dict[str, Any]:
        per_person: Dict[str, Dict[str, Any]] = {}
        recent: List[Dict[str, Any]] = []

        records = sorted(self._history, key=lambda r: r["date"])
        for r in records:
            seen = set()
            switched = bool(r["auto_group_name"]) and r["group_name"] != r["auto_group_name"]
            members_out = []
            for m in r["members"]:
                members_out.append({"name": m["name"], "task": m["task"], "status": m["status"]})
                if not m["name"] or m["name"] in seen:
                    continue
                seen.add(m["name"])
                entry = per_person.setdefault(m["name"], {
                    "name": m["name"], "count": 0, "absent": 0,
                })
                entry["count"] += 1
                if m["status"] == STATUS_ABSENT:
                    entry["absent"] += 1
            recent.append({
                "date": r["date"],
                "groupName": r["group_name"],
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

        self._history = []
        self._history_timer.stop()
        self._flush_history()
        logger.info("[值日生] 历史记录已清空")
        self._emit_duty_changed()

    # -------------------------------------------------------- import/export
    @Slot(str, result="QVariant")
    def export_config(self, path: str) -> Dict[str, Any]:
        """把分组、轮换、假期导出为 JSON 文件（不含 manual_offset / history）。"""
        import os
        from loguru import logger

        try:
            path = os.path.expanduser(path.strip())
            if not path:
                return {"ok": False, "msg": "路径不能为空"}

            data = {
                "groups": [
                    {
                        "name": g.name,
                        "members": [
                            {"name": m.name, "task": m.task}
                            for m in g.members
                        ],
                    }
                    for g in self.config.groups
                ],
                "start_date": self.config.start_date,
                "rotation_mode": self.config.rotation_mode,
                "holidays": [
                    {"start": h.start, "end": h.end, "name": h.name}
                    for h in self.config.holidays
                ],
            }

            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"[值日生] 配置已导出到 {path}")
            return {"ok": True, "msg": path}
        except Exception as e:
            logger.error(f"[值日生] 导出失败: {e}")
            return {"ok": False, "msg": str(e)}

    @Slot(str, result="QVariant")
    def import_config(self, path: str) -> Dict[str, Any]:
        """从 JSON 文件导入分组、轮换、假期。"""
        import os
        from loguru import logger

        try:
            path = os.path.expanduser(path.strip())
            if not path or not os.path.isfile(path):
                return {"ok": False, "msg": "文件不存在"}

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return {"ok": False, "msg": "格式无效：根对象不是字典"}

            groups_raw = data.get("groups")
            if not isinstance(groups_raw, list):
                return {"ok": False, "msg": "格式无效：groups 不是数组"}

            groups: List[DutyGroup] = []
            for g in groups_raw:
                if not isinstance(g, dict):
                    continue
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

            holidays_raw = data.get("holidays", [])
            holidays: List[Holiday] = []
            if isinstance(holidays_raw, list):
                for h in holidays_raw:
                    if not isinstance(h, dict):
                        continue
                    holidays.append(Holiday(
                        start=str(h.get("start", "") or ""),
                        end=str(h.get("end", "") or h.get("start", "") or ""),
                        name=str(h.get("name", "") or ""),
                    ))

            with self._batch_config_update():
                self.config.groups = groups
                self.config.start_date = str(
                    data.get("start_date", "") or self.config.start_date
                )
                mode = str(data.get("rotation_mode", "") or "")
                self.config.rotation_mode = (
                    mode if mode in VALID_MODES else self.config.rotation_mode
                )
                self.config.holidays = holidays
                self.config.manual_offset = 0

            logger.info(
                f"[值日生] 配置已导入：{len(groups)} 组, {len(holidays)} 个假期, "
                f"模式={self.config.rotation_mode}, 起始={self.config.start_date}"
            )
            self._persist()
            return {"ok": True, "msg": f"导入成功：{len(groups)} 组, {len(holidays)} 个假期"}
        except Exception as e:
            logger.error(f"[值日生] 导入失败: {e}")
            return {"ok": False, "msg": str(e)}
