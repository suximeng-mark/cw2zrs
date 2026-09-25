from __future__ import annotations

import json
import os
import re
from bisect import bisect_right
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
# 设定分钟后的宽限窗口（分钟）：轮询若因挂起/休眠/阻塞错过设定分钟，
# 仍在窗口内则补推；窗口外（如下午才启动）视为过期，不再打扰
REMINDER_GRACE_MIN = 10

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
    "font_meta": 12,                # 次数 / 假期 / 已调换徽标
    "font_name": 14,                # 成员姓名
    "font_task": 14,                # 任务
    "show_group": True,             # 组名显示
    "show_name": True,              # 姓名显示
    "show_task": True,              # 职责显示
    "show_meta": True,              # 次数（第N周/轮/天）显示
    "member_layout": LAYOUT_TASK,   # 普通模式成员排列方式
    "pair_style": PAIR_PAREN,       # 姓名与任务的一一对应样式
    "show_tomorrow": False,         # 部件中显示明日值日预告
    "reminder_enabled": False,      # 每日值日提醒开关
    "reminder_time": REMINDER_DEFAULT_TIME,
    "reminder_skip_holiday": True,  # 假期不提醒
}

# 工作日轮换的周末处理方式：
# merge=周六日整体计 1 档（默认） / skip=周末不轮换 / each=周六日逐日计档
WEEKEND_MERGE = "merge"
WEEKEND_SKIP = "skip"
WEEKEND_EACH = "each"
VALID_WEEKEND_MODES = (WEEKEND_MERGE, WEEKEND_SKIP, WEEKEND_EACH)

# 轮换步长（每档单位数）：多少个轮换单位算作「一次值日」
# 1=每单位换一次（默认）；2=同一组连续值日 2 天/2 周后再换（两天算一次值日）
# 单位随轮换周期变化：每日/工作日轮换=天，每周轮换=周
DEFAULT_SLOT_DAYS = 1
SLOT_DAYS_MIN = 1
SLOT_DAYS_MAX = 12
# 设置页下拉可选档位（覆盖日常使用，后端上限更宽以兼容旧备份）
SLOT_DAYS_CHOICES = (1, 2, 3, 4, 5, 6)

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
        self._start_day: date = date.fromisoformat(DEFAULT_START_DATE)  # 解析缓存
        self._rotation_mode: str = MODE_WEEKLY
        # 工作日轮换的周末处理（merge/skip/each），见 VALID_WEEKEND_MODES
        self._weekend_mode: str = WEEKEND_MERGE
        # 轮换步长：每 N 个轮换单位（天/周）算一次值日，1=每单位轮换
        self._slot_days: int = DEFAULT_SLOT_DAYS
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
        # 假期二分索引缓存（惰性构建，随 fingerprint 一起失效）
        self._holiday_idx: Optional[tuple] = None
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

        # 组件显隐（仅接受显式布尔，缺省保留 base 中的值）
        for key in ("show_group", "show_name", "show_task", "show_meta"):
            if isinstance(raw.get(key), bool):
                out[key] = raw[key]

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
        self._set_start_date(start if DATE_RE.fullmatch(start) else DEFAULT_START_DATE)

        mode = str(data.get("rotation_mode", "") or "")
        self._rotation_mode = mode if mode in VALID_MODES else MODE_WEEKLY

        wm = str(data.get("weekend_mode", "") or "")
        self._weekend_mode = wm if wm in VALID_WEEKEND_MODES else WEEKEND_MERGE

        # 轮换步长：缺省/脏值回退 1（每单位轮换），保持旧配置行为不变
        self._slot_days = self._clamp_slot_days(data.get("slot_days"))

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
        self._invalidate_holiday_cache()

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
            "weekend_mode": self._weekend_mode,
            "slot_days": self._slot_days,
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
    def _set_start_date(self, value: str) -> None:
        """设置起始日期并缓存解析结果，避免 _elapsed_slots 高频调用重复 strptime。"""
        self._start_date = value
        self._start_day = self._parse_date(value)

    def _parse_date(self, date_str: str) -> date:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return date.today()

    @staticmethod
    def _clamp_slot_days(value: Any) -> int:
        """轮换步长归一化：非法/越界值回退 DEFAULT_SLOT_DAYS 或就近截断。"""
        if value is None or value == "":
            return DEFAULT_SLOT_DAYS
        try:
            n = int(value)
        except (ValueError, TypeError):
            return DEFAULT_SLOT_DAYS
        return max(SLOT_DAYS_MIN, min(SLOT_DAYS_MAX, n))

    def _holiday_index(self) -> tuple:
        """惰性构建假期索引（随假期数据变化失效），替代逐日线性扫描。

        返回 (merged_starts, merged)：重叠/相邻的假期区间合并为无重叠的
        [(start, end)] 升序列表，可二分精确判定任意日期是否被覆盖，
        也支持整段跳过与分段计数。
        """
        idx = self._holiday_idx
        if idx is not None:
            return idx
        ranges: List[tuple] = []
        for h in self._holidays:
            try:
                s = date.fromisoformat(h.start)
                e = date.fromisoformat(h.end or h.start)
            except ValueError:
                continue
            if e < s:
                s, e = e, s
            ranges.append((s, e))
        ranges.sort()
        merged: List[tuple] = []
        for s, e in ranges:
            # 相邻（touching）也合并：整周/整段判定依赖并集语义
            if merged and s <= merged[-1][1] + timedelta(days=1):
                if e > merged[-1][1]:
                    merged[-1] = (merged[-1][0], e)
            else:
                merged.append((s, e))
        idx = ([m[0] for m in merged], merged)
        self._holiday_idx = idx
        return idx

    def _invalidate_holiday_cache(self) -> None:
        """假期数据变化后使 fingerprint 与二分索引同时失效。"""
        self._holidays_fp = None
        self._holiday_idx = None

    def _find_holiday(self, day: date) -> Optional[Holiday]:
        """返回覆盖该日期的假期配置；非假期返回 None。

        保持原始“按列表序首个覆盖”语义（重叠区间时名称显示与旧版一致）：
        先用合并区间 O(log H) 排除非假期（常见路径），命中时再线性扫描取对象。
        """
        merged_starts, merged = self._holiday_index()
        i = bisect_right(merged_starts, day) - 1
        if i < 0 or day > merged[i][1]:
            return None
        iso = day.isoformat()
        for h in self._holidays:
            if h.start and h.start <= iso <= (h.end or h.start):
                return h
        return None

    def _is_holiday(self, day: date) -> bool:
        """O(log H)：在合并后的无重叠区间上二分判定。"""
        merged_starts, merged = self._holiday_index()
        i = bisect_right(merged_starts, day) - 1
        return i >= 0 and day <= merged[i][1]

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

        最后按轮换步长（slot_days）折算：每 N 个单位才算一次值日
        （N=2 即同一组连续值日 2 天/2 周后再轮换）。

        结果按 (起始日期, 模式, 周末处理, 步长, 假期, 目标日期) 缓存，
        同一天的重复调用为 O(1)。
        """
        start = self._start_day
        today = today or date.today()
        if today <= start:
            return 0

        fingerprint = (
            self._start_date,
            self._rotation_mode,
            self._weekend_mode,
            self._slot_days,
            self._holidays_fingerprint(),
            today.isoformat(),
        )
        cached = self._slots_cache.get(fingerprint)
        if cached is not None:
            self._slots_cache.move_to_end(fingerprint)
            return cached

        units = self._compute_elapsed_slots(start, today)
        slots = units // self._slot_days if self._slot_days > 1 else units
        self._slots_cache[fingerprint] = slots
        if len(self._slots_cache) > SLOTS_CACHE_LIMIT:
            self._slots_cache.popitem(last=False)
        return slots

    def _slot_progress(self, day: date) -> tuple:
        """当前这一「次值日」的进度：(档内第几个单位, 每档单位数)。

        步长=1 时恒为 (1, 1)；步长=2 时连续两天返回 (1, 2)、(2, 2)，
        便于部件显示「第 3 次（1/2）」。
        """
        step = self._slot_days
        if step <= 1 or day <= self._start_day:
            return 1, step if step > 1 else 1
        units = self._compute_elapsed_slots(self._start_day, day)
        return units % step + 1, step

    def _compute_elapsed_slots(self, start: date, today: date) -> int:
        """按模式计算 (start, today] 内的轮换档数。

        daily/weekly 为闭式公式（O(H)，与跨度天数无关）；
        workday 逐日但假期整段跳过（迭代次数 ≈ 非假期天数 + 假期段数）。
        语义与旧逐日实现完全一致（由 tests/test_rotation.py 差分验证）。
        """
        mode = self._rotation_mode
        days = (today - start).days
        if days <= 0:
            return 0
        merged_starts, merged = self._holiday_index()
        one = timedelta(days=1)

        if mode == MODE_DAILY:
            # 总天数 - 窗口内假期天数（合并区间逐段裁剪求交）
            holiday_days = 0
            win_start = start + one
            for s, e in merged:
                lo = s if s > win_start else win_start
                hi = e if e < today else today
                if hi >= lo:
                    holiday_days += (hi - lo).days + 1
            return days - holiday_days

        if mode == MODE_WEEKLY:
            # 区块 k = [start+7k, start+7k+6]，k = 1..days//7；整周都是假期才跳过
            k_max = days // 7
            covered = 0
            for s, e in merged:
                # 完全落在假期内的周：start+7k >= s 且 start+7k+6 <= e
                # 即 k >= ceil((s-start)/7) 且 k <= floor((e-start-6)/7)
                lo = max(((s - start).days + 6) // 7, 1)
                hi = min(((e - start).days - 6) // 7, k_max)
                if hi >= lo:
                    covered += hi - lo + 1
            return k_max - covered

        # workday：非假期每天一档；周末处理由 _weekend_mode 决定
        # each=周末逐日计档，等价于所有非假期日 +1（与 daily 同公式）
        if self._weekend_mode == WEEKEND_EACH:
            holiday_days = 0
            win_start = start + one
            for s, e in merged:
                lo = s if s > win_start else win_start
                hi = e if e < today else today
                if hi >= lo:
                    holiday_days += (hi - lo).days + 1
            return days - holiday_days

        slots = 0
        count_weekend = self._weekend_mode != WEEKEND_SKIP
        cur = start + one
        while cur <= today:
            i = bisect_right(merged_starts, cur) - 1
            if i >= 0 and cur <= merged[i][1]:
                cur = merged[i][1] + one  # 整段假期跳过
                continue
            wd = cur.weekday()
            if wd < 5:
                slots += 1
            elif count_weekend:
                if wd == 5:
                    slots += 1  # 周六代表整个周末档
                else:  # 周日：仅当其周六为假期（周六被跳过、未计档）且晚于起始日时补一档
                    saturday = cur - one
                    if cur > start + one and self._is_holiday(saturday):
                        slots += 1
            cur += one
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
            "showGroup": bool(s.get("show_group", True)),
            "showName": bool(s.get("show_name", True)),
            "showTask": bool(s.get("show_task", True)),
            "showMeta": bool(s.get("show_meta", True)),
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
        self, today: date, auto_idx: int, group: DutyGroup
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
            # 轮换步长：>1 时 periodNumber 表示「第几次值日」，
            # slotPosition 为本次值日中的第几个单位（1..slotDays）
            "slotDays": self._slot_days,
            "slotPosition": self._slot_progress(today)[0],
        }
        result.update(self._display_payload())

        if found:
            slots, idx, group, auto_idx, is_swap = found
            # 纯内存 + 独立文件防抖写；不调用 config.save()，不触发 configChanged
            record = self._ensure_today_record(today, auto_idx, group)
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
            self._set_start_date(start if DATE_RE.fullmatch(start) else DEFAULT_START_DATE)
            self._rotation_mode = (
                rotation_mode if rotation_mode in VALID_MODES else MODE_WEEKLY
            )
            self._groups = groups
            self._slots_cache.clear()
            self._invalidate_holiday_cache()
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

    @Slot(result=str)
    def get_weekend_mode(self) -> str:
        """工作日轮换的周末处理方式：merge / skip / each。"""
        return self._weekend_mode

    @Slot(str, result=bool)
    def save_weekend_mode(self, mode: str) -> bool:
        mode = str(mode or "").strip()
        if mode not in VALID_WEEKEND_MODES:
            logger.error(f"[值日生] 周末处理方式无效：{mode!r}")
            return False
        self._weekend_mode = mode
        self._slots_cache.clear()
        self._persist()
        logger.info(f"[值日生] 周末处理方式已保存：{mode}")

    @Slot(result=int)
    def get_slot_days(self) -> int:
        """轮换步长：每 N 个轮换单位（天/周）算一次值日。"""
        return self._slot_days

    @Slot(int, result=bool)
    def save_slot_days(self, value: int) -> bool:
        """设置轮换步长（如 2 = 两天算一次值日）。越界/非法值直接拒绝。"""
        if isinstance(value, bool) or not isinstance(value, int):
            try:
                value = int(str(value).strip())
            except (ValueError, TypeError):
                logger.error(f"[值日生] 轮换步长无效：{value!r}")
                return False
        if not SLOT_DAYS_MIN <= value <= SLOT_DAYS_MAX:
            logger.error(f"[值日生] 轮换步长越界：{value}")
            return False
        if value != self._slot_days:
            self._slot_days = value
            self._slots_cache.clear()
            self._persist()
            logger.info(f"[值日生] 轮换步长已保存：每 {value} 个单位换一次")
        return True
        return True

    # --------------------------------------------------------- display
    @Slot(result="QVariant")
    def get_display_settings(self) -> Dict[str, Any]:
        return self._display_payload()

    @Slot(bool, bool, bool, bool, int, int, int, int, str, str, bool, result=bool)
    def save_display_settings(
        self,
        show_group: bool,
        show_name: bool,
        show_task: bool,
        show_meta: bool,
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
            "show_group": bool(show_group),
            "show_name": bool(show_name),
            "show_task": bool(show_task),
            "show_meta": bool(show_meta),
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
            self._invalidate_holiday_cache()
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
        """20s 轮询：进入设定时间的宽限窗口且当天未推送过则发一次。

        用「当前时间 >= 设定时间且仍在宽限窗口内」替代精确分钟匹配，
        避免该分钟内程序被挂起/阻塞导致当天提醒永久丢失；
        窗口外（如中午才启动程序）视为过期，不补推旧提醒。
        """
        s = self._settings
        if not s["reminder_enabled"] or self._notifier is None:
            return
        now = datetime.now()
        today_iso = now.date().isoformat()
        if self._reminder_fired_date == today_iso:
            return
        try:
            hh, mm = s["reminder_time"].split(":")
            target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except ValueError:
            return
        late_min = (now - target).total_seconds() / 60.0
        if late_min < 0 or late_min > REMINDER_GRACE_MIN:
            return
        if s["reminder_skip_holiday"] and self._is_holiday(now.date()):
            # 假期跳过，同样标记当日已处理，避免窗口内重复检查
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
                "weekend_mode": self._weekend_mode,
                "slot_days": self._slot_days,
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
            if DATE_RE.fullmatch(start):
                self._set_start_date(start)
            mode = str(data.get("rotation_mode", "") or "")
            if mode in VALID_MODES:
                self._rotation_mode = mode
            wm = str(data.get("weekend_mode", "") or "")
            if wm in VALID_WEEKEND_MODES:
                self._weekend_mode = wm
            self._slot_days = self._clamp_slot_days(data.get("slot_days"))
            self._groups = groups
            self._holidays = holidays
            self._manual_offset = 0
            self._temp_swaps = {}
            self._slots_cache.clear()
            self._invalidate_holiday_cache()

            logger.info(
                f"[值日生] 配置已导入：{len(groups)} 组, {len(holidays)} 个假期, "
                f"模式={self._rotation_mode}, 起始={self._start_date}"
            )
            self._persist()
            return {"ok": True, "msg": f"导入成功：{len(groups)} 组, {len(holidays)} 个假期"}
        except Exception as e:
            logger.error(f"[值日生] 导入失败: {e}")
            return {"ok": False, "msg": str(e)}

    # ----------------------------------------------------- backup / restore
    @Slot(str, bool, bool, bool, bool, result="QVariant")
    def export_backup(
        self, path: str, include_display: bool, include_people: bool,
        include_rotation: bool, include_history: bool,
    ) -> Dict[str, Any]:
        """按勾选分节导出完整备份（JSON），分节结构见 import_backup。"""
        try:
            path = os.path.expanduser(path.strip())
            if not path:
                return {"ok": False, "msg": "路径不能为空"}

            sections: Dict[str, Any] = {}
            if include_display:
                sections["display"] = dict(self._settings)
            if include_people:
                sections["groups"] = self._build_config_payload()["groups"]
            if include_rotation:
                sections["rotation"] = {
                    "start_date": self._start_date,
                    "rotation_mode": self._rotation_mode,
                    "weekend_mode": self._weekend_mode,
                    "slot_days": self._slot_days,
                    "holidays": self._build_config_payload()["holidays"],
                    "temp_swaps": dict(self._temp_swaps),
                }
            if include_history:
                sections["history"] = self._history
            if not sections:
                return {"ok": False, "msg": "请至少勾选一项备份内容"}

            payload = {"type": "duty_backup", "version": 1, "sections": sections}
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            logger.info(f"[值日生] 备份已导出到 {path}")
            return {"ok": True, "msg": path}
        except Exception as e:
            logger.error(f"[值日生] 备份导出失败: {e}")
            return {"ok": False, "msg": str(e)}

    @Slot(str, bool, bool, bool, bool, result="QVariant")
    def import_backup(
        self, path: str, include_display: bool, include_people: bool,
        include_rotation: bool, include_history: bool,
    ) -> Dict[str, Any]:
        """从备份文件按勾选分节恢复；兼容旧版 export_config 平铺格式。"""
        try:
            path = os.path.expanduser(path.strip())
            if not path or not os.path.isfile(path):
                return {"ok": False, "msg": "文件不存在"}

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"ok": False, "msg": "格式无效：根对象不是字典"}

            if data.get("type") == "duty_backup" and isinstance(data.get("sections"), dict):
                sections = data["sections"]
            else:
                # 旧版平铺格式：groups/start_date/rotation_mode/holidays
                sections = {
                    "groups": data.get("groups"),
                    "rotation": {
                        "start_date": data.get("start_date", ""),
                        "rotation_mode": data.get("rotation_mode", ""),
                        "weekend_mode": data.get("weekend_mode", ""),
                        "slot_days": data.get("slot_days", ""),
                        "holidays": data.get("holidays", []),
                    },
                }

            applied: List[str] = []
            if include_display and isinstance(sections.get("display"), dict):
                self._settings = self._normalize_settings(
                    sections["display"], base=self._settings
                )
                applied.append("界面设置")

            if include_people and isinstance(sections.get("groups"), list):
                self._groups = self._parse_groups(sections["groups"])
                applied.append(f"人员设置（{len(self._groups)} 组）")

            rot = sections.get("rotation")
            if include_rotation and isinstance(rot, dict):
                start = str(rot.get("start_date", "") or "").strip()
                if DATE_RE.fullmatch(start):
                    self._set_start_date(start)
                mode = str(rot.get("rotation_mode", "") or "")
                if mode in VALID_MODES:
                    self._rotation_mode = mode
                wm = str(rot.get("weekend_mode", "") or "")
                if wm in VALID_WEEKEND_MODES:
                    self._weekend_mode = wm
                if "slot_days" in rot:
                    self._slot_days = self._clamp_slot_days(rot.get("slot_days"))
                self._holidays = self._parse_holidays(rot.get("holidays", []))
                swaps: Dict[str, int] = {}
                raw_swaps = rot.get("temp_swaps")
                if isinstance(raw_swaps, dict):
                    for d, gi in raw_swaps.items():
                        if DATE_RE.fullmatch(str(d)):
                            try:
                                swaps[str(d)] = int(gi)
                            except (ValueError, TypeError):
                                continue
                self._temp_swaps = swaps
                applied.append("轮换配置及方式")

            if include_history and isinstance(sections.get("history"), list):
                self._history = [
                    self._sanitize_record(r)
                    for r in sections["history"]
                    if self._is_valid_record(r)
                ]
                self._trim_history()
                self._flush_history()
                applied.append(f"请假记录（{len(self._history)} 天）")

            if not applied:
                return {"ok": False, "msg": "备份中没有可导入的所选内容"}

            self._slots_cache.clear()
            self._invalidate_holiday_cache()
            self._persist()
            logger.info(f"[值日生] 备份导入完成：{'、'.join(applied)}")
            return {"ok": True, "msg": "已导入：" + "、".join(applied)}
        except Exception as e:
            logger.error(f"[值日生] 备份导入失败: {e}")
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

            # 轮次：步长 > 1 时同一组内多天共享一个「值日次数」
            period = f"{slots + 1}"
            if self._slot_days > 1:
                pos, _ = self._slot_progress(day)
                period += f"（{pos}/{self._slot_days}）"

            rows.append({
                "date": day.isoformat(),
                "weekday": self.WEEKDAY_CN[day.weekday()],
                "group": group.name,
                "members": members_text,
                "period": period,
                "note": note,
            })
        return rows

    @staticmethod
    def _write_schedule_csv(path: Path, rows: List[Dict[str, str]]) -> None:
        import csv

        # utf-8-sig：Excel/WPS 直接打开中文不乱码
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["日期", "星期", "值日组", "成员（任务）", "备注", "轮次"])
            for r in rows:
                writer.writerow(
                    [
                        r["date"], r["weekday"], r["group"], r["members"],
                        r["note"], r.get("period", ""),
                    ]
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
                f"<td>{esc(r['note'])}</td>"
                f"<td>{esc(r.get('period', ''))}</td></tr>"
            )

        mode_label = self.MODE_LABELS.get(self._rotation_mode, "")
        step = self._slot_days
        if step > 1:
            unit = "周" if self._rotation_mode == MODE_WEEKLY else "天"
            mode_label = f"{mode_label}（每 {step} {unit}换一次）"
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
<thead><tr><th>日期</th><th>星期</th><th>值日组</th><th>成员（任务）</th><th>备注</th><th>轮次</th></tr></thead>
<tbody>
{os.linesep.join(body_rows)}
</tbody>
</table>
</body>
</html>
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)

    @Slot(int, int, result="QVariant")
    def get_month_info(self, year: int, month: int) -> Dict[str, Any]:
        """返回覆盖某月的日历数据（前后补齐整周），供设置页月历使用。

        每天含：日期、日号、星期、是否当月/今日、假期名、是否临时调班、
        当日组名与自动组名（调班时显示对比）。
        """
        try:
            first = date(int(year), int(month), 1)
        except (ValueError, TypeError):
            return {"year": 0, "month": 0, "days": []}
        today = date.today()
        nxt = date(
            first.year + (1 if first.month == 12 else 0),
            1 if first.month == 12 else first.month + 1,
            1,
        )
        last = nxt - timedelta(days=1)
        grid_start = first - timedelta(days=first.weekday())
        grid_end = last + timedelta(days=6 - last.weekday())

        days: List[Dict[str, Any]] = []
        cur = grid_start
        while cur <= grid_end:
            found = self._actual_group_for_day(cur)
            auto_idx = found[3] if found else 0
            days.append({
                "date": cur.isoformat(),
                "day": cur.day,
                "weekday": cur.weekday(),
                "inMonth": cur.year == first.year and cur.month == first.month,
                "isToday": cur == today,
                "holidayName": self._holiday_name(cur),
                "groupName": found[2].name if found else "",
                "autoGroupName": self._groups[auto_idx].name if found else "",
                "isSwap": bool(found and found[4]),
            })
            cur += timedelta(days=1)
        return {"year": first.year, "month": first.month, "days": days}

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

    @Slot(int, str, result="QVariant")
    def export_schedule(self, weeks: int, out_dir: str = "") -> Dict[str, Any]:
        """导出未来 N 周值日表（CSV + HTML）。

        out_dir 为空时回落到系统桌面，保持与旧调用方式兼容。
        """
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
            target = str(out_dir or "").strip()
            out_dir_path = (
                Path(os.path.expanduser(target)) if target else self._desktop_dir()
            )
            out_dir_path.mkdir(parents=True, exist_ok=True)
            csv_path = out_dir_path / f"{base}.csv"
            html_path = out_dir_path / f"{base}.html"
            self._write_schedule_csv(csv_path, rows)
            self._write_schedule_html(html_path, rows, start_day, end_day, weeks)

            logger.info(f"[值日生] 值日表已导出：{csv_path.name}, {html_path.name}")
            return {
                "ok": True,
                "msg": f"已导出到：{out_dir_path}\n{csv_path.name}\n{html_path.name}",
            }
        except Exception as e:
            logger.error(f"[值日生] 值日表导出失败: {e}")
            return {"ok": False, "msg": str(e)}
