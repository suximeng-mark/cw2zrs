from __future__ import annotations

import json
import os
import re
from bisect import bisect_left
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ClassWidgets.SDK import ConfigBaseModel, CW2Plugin, PluginAPI
from PySide6.QtCore import QTimer, Signal, Slot

try:  # CW2 运行环境自带 loguru；缺省时退回标准库 logger，避免插件直接崩溃
    from loguru import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("duty_show")

MODE_WEEKLY = "weekly"
MODE_DAILY = "daily"
MODE_WORKDAY = "workday"
VALID_MODES = (MODE_WEEKLY, MODE_DAILY, MODE_WORKDAY)

STATUS_NORMAL = "normal"
STATUS_ABSENT = "absent"

HISTORY_LIMIT = 400
HISTORY_FLUSH_DELAY_MS = 1500
# 插件私有配置（分组/假期/轮换/显示/提醒）落盘防抖：快速连续修改时合并写
CONFIG_FLUSH_DELAY_MS = 400
SLOTS_CACHE_LIMIT = 256

# 成员排列方式：inline=全部合并一行 / task=按岗位分行 / person=每人一行
LAYOUT_INLINE = "inline"
LAYOUT_TASK = "task"
LAYOUT_PERSON = "person"
VALID_LAYOUTS = (LAYOUT_INLINE, LAYOUT_TASK, LAYOUT_PERSON)

FONT_MIN = 9
FONT_MAX = 28

DEFAULT_START_DATE = "2025-09-01"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# 每日值日提醒：轮询间隔与默认时间（HH:MM）
REMINDER_POLL_MS = 20_000
REMINDER_DEFAULT_TIME = "07:30"
REMINDER_DURATION_MS = 8000
REMINDER_PUSH_LEVEL = 1  # NotificationLevel.ANNOUNCEMENT（避免旧版无枚举导入）
REMINDER_TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")

# 姓名与任务的配对样式：paren=姓名（任务）/ dot=姓名·任务 /
# columns=两列对齐 / taskfirst=任务：姓名
PAIR_PAREN = "paren"
PAIR_DOT = "dot"
PAIR_COLUMNS = "columns"
PAIR_TASKFIRST = "taskfirst"
VALID_PAIR_STYLES = (PAIR_PAREN, PAIR_DOT, PAIR_COLUMNS, PAIR_TASKFIRST)

# 显示/提醒设置默认值（随私有配置一起存放在 data/config.json，不进核心 configs.json）
DEFAULT_SETTINGS: Dict[str, Any] = {
    "font_group": 12,               # 组名胶囊（底部按钮跟随）
    "font_meta": 12,                # 周期 / 假期 / 已调换徽标
    "font_name": 14,                # 成员姓名
    "font_task": 14,                # 任务
    "member_layout": LAYOUT_TASK,   # 普通模式成员排列方式
    "pair_style": PAIR_PAREN,       # 姓名与任务的一一对应样式
    "show_tomorrow": False,         # 部件中显示明日值日预告
    "reminder_enabled": False,      # 每日值日提醒开关
    "reminder_time": REMINDER_DEFAULT_TIME,
    "reminder_skip_holiday": True,  # 假期不提醒
}

# 首次安装时的内置示例分组
DEFAULT_GROUPS_RAW = [
    {
        "name": "第1组",
        "members": [
            {"name": "张三", "task": "扫地"},
            {"name": "李四", "task": "擦黑板"},
            {"name": "王五", "task": "倒垃圾"},
        ],
    },
    {
        "name": "第2组",
        "members": [
            {"name": "赵六", "task": "扫地"},
            {"name": "钱七", "task": "擦黑板"},
            {"name": "孙八", "task": "倒垃圾"},
        ],
    },
]


def _object_to_builtin(o: Any) -> Any:
    """json.dumps 的 default 钩子：把 QML 传来的 QVariant 包装对象转成内建类型。"""
    if hasattr(o, "__dict__"):
        return vars(o)
    return str(o)


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


# 注册给 Class Widgets 的是一个“零字段空模型”，仅作占位：
# 核心机制（src.core.plugin.components.register_plugin_model）在绑定回调后会
# 立即执行一次同步——把 RootConfig 内存中 plugins.configs[pid] 替换为
# model.model_dump()（空模型即 {}），随后核心每次落盘都会把这个空段写回
# configs.json。这样本插件的任何数据都不进入核心配置：
#   1. QML 全局单例 Configs.data 的 getter 每次被读取都会对整个 RootConfig
#      全量 model_dump 并转 QVariant（隐藏/显示部件时 94 处绑定批量重评估，
#      基件 Widget.qml 就有 6 处）；插件数据越大卡顿越明显。空段 = 零开销。
#   2. 插件配置完全自包含于私有文件 data/config.json（与 data/history.json
#      同级），备份/迁移/替换测试数据都只需动插件自己的文件夹。
class DutyConfig(ConfigBaseModel):
    pass


class Plugin(CW2Plugin):
    dutyChanged = Signal()

    def __init__(self, api: PluginAPI) -> None:
        super().__init__(api)
        # 仅用于“占位注册”的空模型：注册后核心会把本插件在 RootConfig 中的
        # 配置段清成 {}。真正的配置全部在插件私有文件 data/config.json 中。
        self.config = DutyConfig()

        # ---- 全部插件配置（纯 Python 对象 + 私有文件 data/config.json）----
        self._groups: List[DutyGroup] = []
        self._holidays: List[Holiday] = []
        self._start_date: str = DEFAULT_START_DATE
        self._rotation_mode: str = MODE_WEEKLY
        self._manual_offset: int = 0
        # 临时调班：{date_iso: group_index}，仅覆盖当日自动轮换结果
        self._temp_swaps: Dict[str, int] = {}
        self._settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        plugin_dir = Path(__file__).resolve().parent
        self._data_dir = plugin_dir / "data"
        self._config_file = self._data_dir / "config.json"
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.timeout.connect(self._flush_config)

        # history 为纯 dict 列表：{date, group_name, auto_group_name,
        # members: [{name, task, status}]}
        self._history: List[Dict[str, Any]] = []
        self._history_path = self._data_dir / "history.json"
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.timeout.connect(self._flush_history)
        # _elapsed_slots 结果缓存：fingerprint + 日期 -> 档位数（OrderedDict 实现 LRU）
        self._slots_cache: "OrderedDict[tuple, int]" = OrderedDict()
        # 假期 fingerprint 缓存：仅当假期列表变化时重建（_elapsed_slots 每次调用无需重排序）
        self._holidays_fp: Optional[tuple] = None
        # 每日提醒：通知提供者（旧版核心可能无 notification API，注册失败则降级）
        self._notifier = None
        self._reminder_fired_date = ""
        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(REMINDER_POLL_MS)
        self._reminder_timer.timeout.connect(self._check_reminder)

    def on_load(self) -> None:
        super().on_load()
        if self.pid is None:
            return

        # 必须在 register_plugin_model 之前迁移：注册空模型后核心会立即用 {}
        # 覆盖内存中该插件的整个配置段，旧数据必须先搬进私有文件。
        had_legacy_history = self._migrate_legacy_history(self.pid)
        had_legacy_config = self._migrate_plugin_config(self.pid)

        # 注册零字段空模型：register_plugin_model 绑定回调后会立即执行一次
        # 同步，把 RootConfig 内存里的本插件配置段替换为 {}；核心下次落盘时
        # configs.json 中的本插件段即为空，插件数据全部留在自己的文件夹。
        self.api.config.register_plugin_model(self.pid, self.config)

        if had_legacy_history or had_legacy_config:
            # 立即把瘦身后（本插件段为 {}）的核心配置写盘一次
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

        # 通知注册失败（旧版核心）不影响其余功能
        self._register_notifier()
        self._reminder_timer.start()

    def on_unload(self) -> None:
        # 每一步独立保护：任一环节失败都不能阻断其余落盘与基类卸载
        self._safe_shutdown(self._reminder_timer.stop)
        if self._config_timer.isActive():
            self._config_timer.stop()
            self._safe_shutdown(self._flush_config)
        if self._history_timer.isActive():
            self._history_timer.stop()
            self._safe_shutdown(self._flush_history)
        super().on_unload()

    @staticmethod
    def _safe_shutdown(action) -> None:
        try:
            action()
        except Exception as e:
            logger.warning(f"[值日生] 卸载时操作失败：{e}")

    # ----------------------------------------- plugin config (own folder)
    def _configs_path(self) -> Path:
        # 生产环境：__file__ 位于 <CW根>/plugins/<plugin_id>/main.py
        return Path(__file__).resolve().parents[2] / "configs" / "configs.json"

    def _read_legacy_plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """读取 configs.json 中该插件的旧配置段（仅用于一次性迁移）。"""
        try:
            with open(self._configs_path(), "r", encoding="utf-8") as f:
                root_cfg = json.load(f)
            plugin_cfgs = root_cfg.get("plugins", {}).get("configs", {})
            old_cfg = plugin_cfgs.get(plugin_id) if isinstance(plugin_cfgs, dict) else None
            return old_cfg if isinstance(old_cfg, dict) else {}
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            return {}

    @staticmethod
    def _parse_groups(raw: Any) -> List[DutyGroup]:
        """把 QML/JSON 传来的分组数据解析为 DutyGroup 列表（容错、去脏值）。"""
        if not isinstance(raw, list):
            raise ValueError(f"groups data must be a list, got {type(raw)}")
        groups: List[DutyGroup] = []
        for g in raw:
            if not isinstance(g, dict):
                raise ValueError(f"group must be a dict, got {type(g)}")
            members = [
                DutyMember(
                    name=str(m.get("name", "") or ""),
                    task=str(m.get("task", "") or ""),
                )
                for m in (g.get("members") or [])
                if isinstance(m, dict)
            ]
            groups.append(DutyGroup(
                name=str(g.get("name", "") or "未命名组"),
                members=members,
            ))
        return groups

    @staticmethod
    def _parse_holidays(raw: Any) -> List[Holiday]:
        """把 JSON 数据解析为合法日期区间的 Holiday 列表（非法项丢弃、按开始日排序）。"""
        if not isinstance(raw, list):
            return []

        def _day(value: Any) -> Optional[date]:
            try:
                return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

        normalized: List[Holiday] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            start = _day(item.get("start", ""))
            if start is None:
                continue
            end_raw = str(item.get("end", "") or "").strip()
            end = _day(end_raw) if end_raw else start
            if end is None:
                continue
            if end < start:
                start, end = end, start
            normalized.append(Holiday(
                start=start.isoformat(),
                end=end.isoformat(),
                name=str(item.get("name", "") or "").strip(),
            ))
        normalized.sort(key=lambda h: h.start)
        return normalized

    @staticmethod
    def _normalize_settings(
        raw: Any, base: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """从任意 dict 提取合法的显示/提醒设置。

        合法值覆盖；脏值/非法枚举忽略并保留 base 中的值（加载文件时 base 为
        默认值，保存时调用方传入当前设置——非法输入回退现值而非默认值）。
        """
        raw = raw if isinstance(raw, dict) else {}
        out = dict(base or DEFAULT_SETTINGS)

        def clamp_font(key: str) -> None:
            try:
                out[key] = max(FONT_MIN, min(FONT_MAX, int(raw.get(key, out[key]))))
            except (ValueError, TypeError):
                pass

        for font_key in ("font_group", "font_meta", "font_name", "font_task"):
            clamp_font(font_key)

        layout = str(raw.get("member_layout", "") or "")
        if layout in VALID_LAYOUTS:
            out["member_layout"] = layout
        pair = str(raw.get("pair_style", "") or "")
        if pair in VALID_PAIR_STYLES:
            out["pair_style"] = pair

        if isinstance(raw.get("show_tomorrow"), bool):
            out["show_tomorrow"] = raw["show_tomorrow"]
        if isinstance(raw.get("reminder_enabled"), bool):
            out["reminder_enabled"] = raw["reminder_enabled"]
        if isinstance(raw.get("reminder_skip_holiday"), bool):
            out["reminder_skip_holiday"] = raw["reminder_skip_holiday"]

        time_str = str(raw.get("reminder_time", "") or "").strip()
        if REMINDER_TIME_RE.fullmatch(time_str):
            out["reminder_time"] = time_str
        return out

    def _apply_config(self, data: Dict[str, Any]) -> None:
        """把归一化后的私有配置 dict 应用到内存（任何脏值都回退默认）。"""
        try:
            groups = self._parse_groups(data.get("groups"))
        except (ValueError, TypeError):
            groups = []
        self._groups = groups

        start = str(data.get("start_date", "") or "").strip()
        self._start_date = start if DATE_RE.fullmatch(start) else DEFAULT_START_DATE

        mode = str(data.get("rotation_mode", "") or "")
        self._rotation_mode = mode if mode in VALID_MODES else MODE_WEEKLY

        try:
            self._manual_offset = int(data.get("manual_offset", 0) or 0)
        except (ValueError, TypeError):
            self._manual_offset = 0

        self._holidays = self._parse_holidays(data.get("holidays", []))
        self._settings = self._normalize_settings(data.get("settings", {}))
        raw_swaps = data.get("temp_swaps")
        swaps: Dict[str, int] = {}
        if isinstance(raw_swaps, dict):
            for d, gi in raw_swaps.items():
                if DATE_RE.fullmatch(str(d)):
                    try:
                        swaps[str(d)] = int(gi)
                    except (ValueError, TypeError):
                        continue
        self._temp_swaps = swaps
        self._slots_cache.clear()
        self._holidays_fp = None

    def _load_config_file(self) -> Optional[Dict[str, Any]]:
        try:
            with open(self._config_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (FileNotFoundError, OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _build_config_payload(self) -> Dict[str, Any]:
        return {
            "groups": [
                {
                    "name": g.name,
                    "members": [
                        {"name": m.name, "task": m.task}
                        for m in g.members
                    ],
                }
                for g in self._groups
            ],
            "holidays": [
                {"start": h.start, "end": h.end, "name": h.name}
                for h in self._holidays
            ],
            "start_date": self._start_date,
            "rotation_mode": self._rotation_mode,
            "manual_offset": self._manual_offset,
            "temp_swaps": dict(self._temp_swaps),
            "settings": dict(self._settings),
        }

    def _flush_config(self) -> None:
        """把全部插件配置写入私有文件 data/config.json（原子替换，文件很小）。"""
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            payload = self._build_config_payload()
            tmp_path = self._config_file.with_name(self._config_file.name + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._config_file)
        except Exception as e:
            logger.warning(f"[值日生] 私有配置写入失败: {e}")

    def _schedule_config_flush(self) -> None:
        self._config_timer.start(CONFIG_FLUSH_DELAY_MS)

    def _migrate_plugin_config(self, plugin_id: str) -> bool:
        """私有文件 data/config.json 优先；首次运行时从 configs.json 一次性迁移。

        必须在 register_plugin_model 之前调用（注册空模型会立刻清空核心内存
        中的旧配置段）。返回核心 configs.json 中该插件段是否非空（调用方据此
        保存一次以立即瘦身 configs.json）。
        """
        legacy_cfg = self._read_legacy_plugin_config(plugin_id)
        legacy_present = bool(legacy_cfg)

        file_payload = self._load_config_file()
        if file_payload is not None:
            # 私有文件为权威数据源；configs.json 里的残留段仅待核心保存时清空
            self._apply_config(file_payload)
            return legacy_present

        if legacy_present:
            # 旧版把业务字段与显示/提醒字段平铺在插件配置段，settings 收进子对象
            payload = dict(legacy_cfg)
            payload["settings"] = {
                key: legacy_cfg[key]
                for key in DEFAULT_SETTINGS
                if key in legacy_cfg
            }
            logger.info("[值日生] 检测到 configs.json 中的旧配置，迁移到插件私有文件")
        else:
            payload = {"groups": DEFAULT_GROUPS_RAW}
        self._apply_config(payload)
        self._flush_config()
        return legacy_present

    # ------------------------------------------------------------------ utils
    def _parse_date(self, date_str: str) -> date:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return date.today()

    def _find_holiday(self, day: date) -> Optional[Holiday]:
        """返回覆盖该日期的假期配置；非假期返回 None（单次扫描）。"""
        iso = day.isoformat()
        for h in self._holidays:
            if h.start and h.start <= iso <= (h.end or h.start):
                return h
        return None

    def _is_holiday(self, day: date) -> bool:
        return self._find_holiday(day) is not None

    def _holiday_name(self, day: date) -> str:
        """假期显示名；非假期返回空串，未命名假期返回“假期”。"""
        h = self._find_holiday(day)
        return (h.name or "假期") if h is not None else ""

    @staticmethod
    def _coerce_data(data: Any) -> Any:
        """QML 入参归一化：JSON 字符串直接解析，其余经序列化往返转成内建类型。"""
        if isinstance(data, (str, bytes, bytearray)):
            return json.loads(data)
        return json.loads(json.dumps(data, default=_object_to_builtin))

    @staticmethod
    def _member_line(group: DutyGroup, empty_text: str = "（无值日成员）") -> str:
        """把组成员拼成“姓名（任务）、姓名（任务）”一行。"""
        labels: List[str] = []
        for m in group.members:
            nm = m.name or "（未命名）"
            labels.append(f"{nm}（{m.task}）" if m.task else nm)
        return "、".join(labels) if labels else empty_text

    def _holidays_fingerprint(self) -> tuple:
        """假期列表的可哈希指纹；变化时缓存自动失效。"""
        fp = self._holidays_fp
        if fp is not None:
            return fp
        fp = tuple(
            sorted((h.start, h.end or h.start) for h in self._holidays)
        )
        self._holidays_fp = fp
        return fp

    def _elapsed_slots(self, today: Optional[date] = None) -> int:
        """从起始日期到 today（不含首日）经历的轮换次数；假期不推进轮换。

        - daily：每个非假期自然日 +1
        - workday：每个非假期工作日 +1；周末（六日）整体最多 +1
        - weekly：以起始日为锚点每 7 天为一周，整周都是假期才跳过

        结果按 (起始日期, 模式, 假期, 目标日期) 缓存，同一天的重复调用为 O(1)。
        """
        start = self._parse_date(self._start_date)
        today = today or date.today()
        if today <= start:
            return 0

        fingerprint = (
            self._start_date,
            self._rotation_mode,
            self._holidays_fingerprint(),
            today.isoformat(),
        )
        cached = self._slots_cache.get(fingerprint)
        if cached is not None:
            self._slots_cache.move_to_end(fingerprint)
            return cached

        slots = self._compute_elapsed_slots(start, today)
        self._slots_cache[fingerprint] = slots
        if len(self._slots_cache) > SLOTS_CACHE_LIMIT:
            self._slots_cache.popitem(last=False)
        return slots

    def _compute_elapsed_slots(self, start: date, today: date) -> int:
        mode = self._rotation_mode
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

    def _group_for_day(self, day: date) -> Optional[tuple]:
        """某一天的值日结果：(已轮换档数, 实际组下标, DutyGroup)；无分组返回 None。

        实际下标 = 自动轮换 + 手动调换偏移，与部件显示完全一致。
        """
        groups = self._groups
        if not groups:
            return None
        slots = self._elapsed_slots(day)
        idx = (slots + self._manual_offset) % len(groups)
        return slots, idx, groups[idx]

    def _actual_group_for_day(self, day: date) -> Optional[tuple]:
        """含临时调班的当日值日：(slots, idx, group, auto_idx, is_swap)。

        若该日期在 _temp_swaps 中存在合法组下标，则覆盖自动轮换结果；
        否则回退到 _group_for_day（自动轮换 + 手动偏移）。
        """
        groups = self._groups
        if not groups:
            return None
        slots, auto_idx, _ = self._group_for_day(day)
        iso = day.isoformat()
        swap_idx = self._temp_swaps.get(iso)
        if swap_idx is not None and 0 <= swap_idx < len(groups):
            return slots, swap_idx, groups[swap_idx], auto_idx, True
        return slots, auto_idx, groups[auto_idx], auto_idx, False

    def _persist(self) -> None:
        # 只写插件私有配置文件（小、防抖），完全不触碰核心 configs.json
        self._schedule_config_flush()
        QTimer.singleShot(0, self.dutyChanged.emit)

    def _emit_duty_changed(self) -> None:
        QTimer.singleShot(0, self.dutyChanged.emit)

    def _display_payload(self) -> Dict[str, Any]:
        s = self._settings
        return {
            "fontGroup": s["font_group"],
            "fontMeta": s["font_meta"],
            "fontName": s["font_name"],
            "fontTask": s["font_task"],
            "memberLayout": s["member_layout"],
            "pairStyle": s["pair_style"],
            "showTomorrow": s["show_tomorrow"],
        }

    def _tomorrow_payload(self, today: date, today_idx: int) -> Optional[Dict[str, Any]]:
        """构造明日预告数据（不含考勤状态，明天的记录尚未生成）。"""
        tom = today + timedelta(days=1)
        found = self._actual_group_for_day(tom)
        if found is None:
            return None
        _, idx, group, _, _ = found
        holiday = self._holiday_name(tom)
        return {
            "date": tom.isoformat(),
            "shortDate": f"{tom.month:02d}-{tom.day:02d}",
            "weekday": self.WEEKDAY_CN[tom.weekday()],
            "groupName": group.name,
            "sameAsToday": idx == today_idx,
            "isHoliday": bool(holiday),
            "holidayName": holiday,
            "members": [
                {"name": m.name, "task": m.task}
                for m in group.members
            ],
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
            logger.warning(f"[值日生] 历史记录写入失败: {e}")

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

        old_cfg = self._read_legacy_plugin_config(plugin_id)
        legacy_raw = old_cfg.get("history") if isinstance(old_cfg.get("history"), list) else []

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
            self._groups[auto_idx].name if self._groups else ""
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
        groups = self._groups
        found = self._actual_group_for_day(today)
        holiday = self._holiday_name(today)  # 今日假期名（空串=非假期），只查一次

        auto_idx = found[3] if found else 0
        result: Dict[str, Any] = {
            "rotationMode": self._rotation_mode,
            "periodNumber": (found[0] + 1) if found else 1,
            "totalGroups": len(groups),
            "autoIndex": auto_idx,
            "currentIndex": 0,
            "groupName": "未配置",
            "members": [],
            "date": today.isoformat(),
            "offset": self._manual_offset,
            "switched": False,
            "isHoliday": bool(holiday),
            "holidayName": holiday,
            "tomorrow": None,
        }
        result.update(self._display_payload())

        if found:
            slots, idx, group, auto_idx, is_swap = found
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
            result["tomorrow"] = self._tomorrow_payload(today, idx)
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
            for g in self._groups
        ]

    @Slot(str, str, "QVariant")
    def save_all(self, start_date: str, rotation_mode: str, data: Any) -> None:
        try:
            groups = self._parse_groups(self._coerce_data(data))

            start = str(start_date or "").strip()
            self._start_date = start if DATE_RE.fullmatch(start) else DEFAULT_START_DATE
            self._rotation_mode = (
                rotation_mode if rotation_mode in VALID_MODES else MODE_WEEKLY
            )
            self._groups = groups
            self._slots_cache.clear()
            self._holidays_fp = None
            logger.info(
                f"[值日生] 保存成功：{len(groups)} 组, 模式={self._rotation_mode}, "
                f"起始日期={self._start_date}"
            )
            self._persist()
        except Exception:
            logger.exception("[值日生] 保存失败")

    @Slot(result=str)
    def get_start_date(self) -> str:
        return self._start_date

    @Slot(result=str)
    def get_rotation_mode(self) -> str:
        return self._rotation_mode

    # --------------------------------------------------------- display
    @Slot(result="QVariant")
    def get_display_settings(self) -> Dict[str, Any]:
        return self._display_payload()

    @Slot(int, int, int, int, str, str, bool, result=bool)
    def save_display_settings(
        self,
        font_group: int,
        font_meta: int,
        font_name: int,
        font_task: int,
        member_layout: str,
        pair_style: str,
        show_tomorrow: bool,
    ) -> bool:
        """保存显示设置到插件私有文件。滑块拖动时高频调用：
        内存即时更新（实时预览），写盘防抖 400ms 合并，不触碰核心配置。"""
        # 以当前值为底（非法枚举回退当前值而非默认值），统一走归一化
        raw = dict(self._settings)
        raw.update({
            "font_group": font_group,
            "font_meta": font_meta,
            "font_name": font_name,
            "font_task": font_task,
            "member_layout": member_layout,
            "pair_style": pair_style,
            "show_tomorrow": bool(show_tomorrow),
        })
        self._settings = self._normalize_settings(raw, base=self._settings)
        self._emit_duty_changed()
        self._schedule_config_flush()
        return True

    @Slot()
    def prev_group(self) -> None:
        if self._groups:
            self._manual_offset -= 1
            self._persist()

    @Slot()
    def next_group(self) -> None:
        if self._groups:
            self._manual_offset += 1
            self._persist()

    @Slot()
    def reset_group(self) -> None:
        self._manual_offset = 0
        self._persist()

    # -------------------------------------------------------------- holidays
    @Slot(result="QVariant")
    def get_holidays(self) -> List[Dict[str, Any]]:
        return [
            {"start": h.start, "end": h.end or h.start, "name": h.name}
            for h in self._holidays
        ]

    @Slot("QVariant", result=bool)
    def save_holidays(self, data: Any) -> bool:
        try:
            normalized = self._parse_holidays(self._coerce_data(data))
            self._holidays = normalized
            self._slots_cache.clear()
            self._holidays_fp = None
            logger.info(f"[值日生] 假期已保存：{len(normalized)} 个时间段")
            self._persist()
            return True
        except Exception as e:
            logger.error(f"[值日生] 假期保存失败: {e}")
            return False

    # --------------------------------------------------------- attendance
    @Slot(str, int, str, result=bool)
    def set_member_status(self, day: str, member_index: int, status: str) -> bool:
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
                    "name": m["name"],
                    "count": 0, "absent": 0,
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
        self._history = []
        self._history_timer.stop()
        self._flush_history()
        logger.info("[值日生] 历史记录已清空")
        self._emit_duty_changed()

    # ------------------------------------------------------------ reminder
    def _register_notifier(self) -> None:
        """注册系统通知提供者；核心不支持 notification API 时静默降级。"""
        if self.pid is None:
            return
        try:
            self._notifier = self.api.notification.register_provider(
                f"{self.pid}.reminder",
                name="值日提醒",
                icon="ic_fluent_alert_20_regular",
                use_system_notify=True,
            )
        except Exception as e:
            self._notifier = None
            logger.warning(f"[值日生] 当前版本不支持通知提醒：{e}")

    def _duty_brief(self, day: date) -> Optional[tuple]:
        """某日提醒文案：(组名, 成员一行文本)；无分组返回 None。"""
        found = self._group_for_day(day)
        if found is None:
            return None
        _, _, group = found
        return group.name, self._member_line(group)

    def _fire_reminder(self, day: date) -> bool:
        if self._notifier is None:
            return False
        brief = self._duty_brief(day)
        if brief is None:
            return False
        group_name, members_text = brief
        lines = [members_text]
        holiday = self._holiday_name(day)  # 同时得到是否假期与名称，只扫一次
        if holiday:
            lines.append(f"今天是{holiday}，请留意值日安排")
        self._notifier.push(
            level=REMINDER_PUSH_LEVEL,
            title=f"今日值日生 · {group_name}",
            message="\n".join(lines),
            duration=REMINDER_DURATION_MS,
            closable=True,
        )
        logger.info(f"[值日生] 已推送值日提醒：{day} {group_name}")
        return True

    def _check_reminder(self) -> None:
        """20s 轮询：到设定分钟且当天未推送过则发一次（轮询保证该分钟内必命中）。"""
        s = self._settings
        if not s["reminder_enabled"] or self._notifier is None:
            return
        now = datetime.now()
        today_iso = now.date().isoformat()
        if self._reminder_fired_date == today_iso:
            return
        if now.strftime("%H:%M") != s["reminder_time"]:
            return
        if s["reminder_skip_holiday"] and self._is_holiday(now.date()):
            # 假期跳过，同样标记当日已处理，避免跨分钟重复检查
            self._reminder_fired_date = today_iso
            return
        try:
            if self._fire_reminder(now.date()):
                self._reminder_fired_date = today_iso
        except Exception as e:
            logger.warning(f"[值日生] 值日提醒推送失败：{e}")

    @Slot(result="QVariant")
    def get_reminder_settings(self) -> Dict[str, Any]:
        s = self._settings
        return {
            "enabled": s["reminder_enabled"],
            "time": s["reminder_time"],
            "skipHoliday": s["reminder_skip_holiday"],
            "supported": self._notifier is not None,
        }

    @Slot(bool, str, bool, result=bool)
    def save_reminder_settings(
        self, enabled: bool, time_str: str, skip_holiday: bool
    ) -> bool:
        try:
            time_str = str(time_str or "").strip()
            if not REMINDER_TIME_RE.fullmatch(time_str):
                logger.error(f"[值日生] 提醒时间格式无效：{time_str!r}")
                return False
            self._settings["reminder_enabled"] = bool(enabled)
            self._settings["reminder_time"] = time_str
            self._settings["reminder_skip_holiday"] = bool(skip_holiday)
            # 让修改后的时间在当天即可生效
            self._reminder_fired_date = ""
            self._schedule_config_flush()
            logger.info(
                f"[值日生] 提醒设置已保存：启用={self._settings['reminder_enabled']}, "
                f"时间={time_str}, 假期跳过={self._settings['reminder_skip_holiday']}"
            )
            return True
        except Exception as e:
            logger.error(f"[值日生] 提醒设置保存失败: {e}")
            return False

    @Slot(result="QVariant")
    def test_reminder(self) -> Dict[str, Any]:
        if self._notifier is None:
            return {"ok": False, "msg": "当前 Class Widgets 版本不支持通知"}
        try:
            ok = self._fire_reminder(date.today())
            return (
                {"ok": True, "msg": "已推送测试提醒，请注意查看通知"}
                if ok else {"ok": False, "msg": "暂无值日分组"}
            )
        except Exception as e:
            logger.error(f"[值日生] 测试提醒失败: {e}")
            return {"ok": False, "msg": str(e)}

    # -------------------------------------------------------- import/export
    @Slot(str, result="QVariant")
    def export_config(self, path: str) -> Dict[str, Any]:
        """把分组、轮换、假期导出为 JSON 文件（不含 manual_offset / history）。"""
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
                    for g in self._groups
                ],
                "start_date": self._start_date,
                "rotation_mode": self._rotation_mode,
                "holidays": [
                    {"start": h.start, "end": h.end, "name": h.name}
                    for h in self._holidays
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
        try:
            path = os.path.expanduser(path.strip())
            if not path or not os.path.isfile(path):
                return {"ok": False, "msg": "文件不存在"}

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return {"ok": False, "msg": "格式无效：根对象不是字典"}

            groups = self._parse_groups(data.get("groups"))
            holidays = self._parse_holidays(data.get("holidays", []))

            start = str(data.get("start_date", "") or "").strip()
            self._start_date = start if DATE_RE.fullmatch(start) else self._start_date
            mode = str(data.get("rotation_mode", "") or "")
            if mode in VALID_MODES:
                self._rotation_mode = mode
            self._groups = groups
            self._holidays = holidays
            self._manual_offset = 0
            self._temp_swaps = {}
            self._slots_cache.clear()
            self._holidays_fp = None

            logger.info(
                f"[值日生] 配置已导入：{len(groups)} 组, {len(holidays)} 个假期, "
                f"模式={self._rotation_mode}, 起始={self._start_date}"
            )
            self._persist()
            return {"ok": True, "msg": f"导入成功：{len(groups)} 组, {len(holidays)} 个假期"}
        except Exception as e:
            logger.error(f"[值日生] 导入失败: {e}")
            return {"ok": False, "msg": str(e)}

    # ----------------------------------------------------- schedule export
    WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    MODE_LABELS = {
        MODE_WEEKLY: "按周轮换",
        MODE_DAILY: "每天轮换",
        MODE_WORKDAY: "工作日轮换",
    }
    SCHEDULE_MAX_WEEKS = 26

    def _desktop_dir(self) -> Path:
        """导出目录：优先系统桌面，取不到时回退用户主目录。"""
        try:
            from PySide6.QtCore import QStandardPaths

            location = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DesktopLocation
            )
            if location:
                return Path(location)
        except Exception:
            pass
        return Path.home()

    def _build_schedule_rows(
        self, start_day: date, weeks: int
    ) -> List[Dict[str, str]]:
        """逐日生成排班行，轮换结果与 widget 完全一致（含手动换组偏移）。"""
        groups = self._groups
        offset = self._manual_offset
        rows: List[Dict[str, str]] = []
        for k in range(weeks * 7):
            day = start_day + timedelta(days=k)
            slots = self._elapsed_slots(day)
            idx = (slots + offset) % len(groups)
            group = groups[idx]

            members_text = self._member_line(group, empty_text="（无成员）")

            holiday = self._holiday_name(day)
            if holiday:
                note = f"假期：{holiday}"
            elif day.weekday() >= 5:
                note = "周末"
            else:
                note = ""

            rows.append({
                "date": day.isoformat(),
                "weekday": self.WEEKDAY_CN[day.weekday()],
                "group": group.name,
                "members": members_text,
                "note": note,
            })
        return rows

    @staticmethod
    def _write_schedule_csv(path: Path, rows: List[Dict[str, str]]) -> None:
        import csv

        # utf-8-sig：Excel/WPS 直接打开中文不乱码
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["日期", "星期", "值日组", "成员（任务）", "备注"])
            for r in rows:
                writer.writerow(
                    [r["date"], r["weekday"], r["group"], r["members"], r["note"]]
                )

    def _write_schedule_html(
        self,
        path: Path,
        rows: List[Dict[str, str]],
        start_day: date,
        end_day: date,
        weeks: int,
    ) -> None:
        import html

        def esc(v: str) -> str:
            return html.escape(v or "", quote=True)

        body_rows = []
        for r in rows:
            if r["note"].startswith("假期"):
                cls = "holiday"
            elif r["note"] == "周末":
                cls = "weekend"
            else:
                cls = "workday"
            body_rows.append(
                f'<tr class="{cls}">'
                f"<td>{esc(r['date'])}</td>"
                f"<td>{esc(r['weekday'])}</td>"
                f"<td>{esc(r['group'])}</td>"
                f"<td>{esc(r['members'])}</td>"
                f"<td>{esc(r['note'])}</td></tr>"
            )

        mode_label = self.MODE_LABELS.get(self._rotation_mode, "")
        generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>班级值日表 {esc(start_day.isoformat())} 起 {weeks} 周</title>
<style>
@page {{ size: A4; margin: 14mm; }}
* {{ box-sizing: border-box; }}
body {{
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    margin: 24px; color: #1B1B1F;
}}
h1 {{ font-size: 22px; margin: 0 0 6px; }}
.meta {{ font-size: 12px; color: #666; margin-bottom: 14px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #C5C6CE; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #EEF3FF; font-weight: 600; white-space: nowrap; }}
td:nth-child(1), td:nth-child(2), td:nth-child(5) {{ white-space: nowrap; }}
tr.holiday td {{ background: #FFF5DC; }}
tr.weekend td {{ background: #F4F4F7; color: #777; }}
@media print {{
    body {{ margin: 0; }}
    tr {{ page-break-inside: avoid; }}
}}
</style>
</head>
<body>
<h1>班级值日表</h1>
<div class="meta">
日期范围：{esc(start_day.isoformat())} ~ {esc(end_day.isoformat())}（共 {weeks} 周）
｜{esc(mode_label)}｜生成时间：{esc(generated)}
</div>
<table>
<thead><tr><th>日期</th><th>星期</th><th>值日组</th><th>成员（任务）</th><th>备注</th></tr></thead>
<tbody>
{os.linesep.join(body_rows)}
</tbody>
</table>
</body>
</html>
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)

    @Slot(result="QVariant")
    def get_week_schedule(self) -> Dict[str, Any]:
        """返回本周（周一~周日）的值日排班，供设置页周历预览。

        每天含：日期、星期、组名、成员（姓名+任务）、是否假期、假期名、
        是否临时调班、自动组名（调班时显示对比）。
        """
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        days: List[Dict[str, Any]] = []
        for i in range(7):
            day = monday + timedelta(days=i)
            found = self._actual_group_for_day(day)
            holiday = self._holiday_name(day)
            entry: Dict[str, Any] = {
                "date": day.isoformat(),
                "weekday": self.WEEKDAY_CN[i],
                "isToday": day == today,
                "isHoliday": bool(holiday),
                "holidayName": holiday,
                "isSwap": False,
                "autoGroupName": "",
                "groupName": "—",
                "members": [],
            }
            if found is not None:
                _, idx, group, auto_idx, is_swap = found
                entry["groupName"] = group.name
                entry["autoGroupName"] = self._groups[auto_idx].name
                entry["isSwap"] = is_swap
                entry["members"] = [
                    {"name": m.name, "task": m.task}
                    for m in group.members
                ]
            days.append(entry)
        return {
            "monday": monday.isoformat(),
            "sunday": (monday + timedelta(days=6)).isoformat(),
            "days": days,
            "totalGroups": len(self._groups),
            "groupNames": [g.name for g in self._groups],
        }

    @Slot(str, int, result=bool)
    def set_temp_swap(self, day: str, group_index: int) -> bool:
        """设置某日的临时调班：group_index=-1 表示清除该日调班。

        仅覆盖当日自动轮换结果，不影响其他日期与轮换计数。
        """
        if not DATE_RE.fullmatch(str(day or "").strip()):
            return False
        iso = str(day).strip()
        n = len(self._groups)
        if n == 0:
            return False
        if group_index < 0:
            self._temp_swaps.pop(iso, None)
        else:
            if group_index >= n:
                return False
            self._temp_swaps[iso] = group_index
        logger.info(f"[值日生] 临时调班：{iso} -> 组{group_index if group_index >= 0 else '(清除)'}")
        self._persist()
        return True

    @Slot(int, result="QVariant")
    def export_schedule(self, weeks: int) -> Dict[str, Any]:
        """导出未来 N 周值日表（CSV + HTML）到桌面。"""
        try:
            weeks = int(weeks)
        except (ValueError, TypeError):
            return {"ok": False, "msg": "周数无效"}
        weeks = max(1, min(self.SCHEDULE_MAX_WEEKS, weeks))

        if not self._groups:
            return {"ok": False, "msg": "请先创建值日小组"}

        try:
            start_day = date.today()
            end_day = start_day + timedelta(days=weeks * 7 - 1)
            rows = self._build_schedule_rows(start_day, weeks)

            base = f"值日表_{start_day.isoformat()}起_{weeks}周"
            out_dir = self._desktop_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
            csv_path = out_dir / f"{base}.csv"
            html_path = out_dir / f"{base}.html"
            self._write_schedule_csv(csv_path, rows)
            self._write_schedule_html(html_path, rows, start_day, end_day, weeks)

            logger.info(f"[值日生] 值日表已导出：{csv_path.name}, {html_path.name}")
            return {
                "ok": True,
                "msg": f"已导出到：{out_dir}\n{csv_path.name}\n{html_path.name}",
            }
        except Exception as e:
            logger.error(f"[值日生] 值日表导出失败: {e}")
            return {"ok": False, "msg": str(e)}
