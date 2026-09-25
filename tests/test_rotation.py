# -*- coding: utf-8 -*-
"""轮换引擎回归测试：优化后 _compute_elapsed_slots 与旧逐日实现差分等价。

运行方式（无需 CW2 环境，桩掉 ClassWidgets.SDK / PySide6.QtCore 即可）：
    python tests/test_rotation.py

覆盖：
  1. 手工核算用例（整周假期、周末合并、起始日为周六等边界）
  2. 随机差分（优化后公式实现 vs 内嵌旧逐日实现，2000 组随机场景）
  3. _is_holiday / _find_holiday 与线性扫描的等价性
  4. 缓存失效（假期变化后 _invalidate_holiday_cache 生效）
  5. 轮换步长 slot_days（两天算一次值日）与档内进度 _slot_progress
"""

import random
import sys
import types
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_stubs() -> None:
    """安装 ClassWidgets.SDK 与 PySide6.QtCore 的桩模块。"""
    sdk_mod = types.ModuleType("ClassWidgets.SDK")

    class ConfigBaseModel:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

        def __repr__(self):  # 便于断言失败时排查
            return f"{type(self).__name__}({self.__dict__!r})"

    class CW2Plugin:
        def __init__(self, api=None):
            self.api = api

    class PluginAPI:  # 测试不触碰
        pass

    sdk_mod.ConfigBaseModel = ConfigBaseModel
    sdk_mod.CW2Plugin = CW2Plugin
    sdk_mod.PluginAPI = PluginAPI

    qtcore_mod = types.ModuleType("PySide6.QtCore")

    class _SignalBound:
        def connect(self, fn):
            pass

        def emit(self, *args):
            pass

    class Signal:
        def __set_name__(self, owner, name):
            pass

        def __get__(self, obj, objtype=None):
            return _SignalBound()

    class _Timer:
        def __init__(self, *args, **kwargs):
            self.timeout = _SignalBound()

        def setSingleShot(self, v):
            pass

        def setInterval(self, ms):
            pass

        def start(self, ms=None):
            pass

        def stop(self):
            pass

        def isActive(self):
            return False

        @staticmethod
        def singleShot(ms, fn=None):
            pass

    def Slot(*args, **kwargs):
        def deco(fn):
            return fn

        return deco

    qtcore_mod.QTimer = _Timer
    qtcore_mod.Signal = Signal
    qtcore_mod.Slot = Slot

    cw_pkg = types.ModuleType("ClassWidgets")
    cw_pkg.SDK = sdk_mod
    pyside_pkg = types.ModuleType("PySide6")
    pyside_pkg.QtCore = qtcore_mod

    sys.modules.setdefault("ClassWidgets", cw_pkg)
    sys.modules.setdefault("ClassWidgets.SDK", sdk_mod)
    sys.modules.setdefault("PySide6", pyside_pkg)
    sys.modules.setdefault("PySide6.QtCore", qtcore_mod)


_install_stubs()

import main as m  # noqa: E402


def make_plugin(
    mode: str, start: str, holidays: list, weekend_mode: str = "merge",
    slot_days: int = 1, merge_pairs: list = None,
) -> "m.Plugin":
    """绕过 __init__ 构造最小可用的 Plugin（仅轮换相关字段）。"""
    p = object.__new__(m.Plugin)
    p._rotation_mode = mode
    p._start_date = start
    p._start_day = m.Plugin._parse_date(p, start)
    p._holidays = m.Plugin._parse_holidays(holidays)
    p._holidays_fp = None
    p._holiday_idx = None
    p._slots_cache = OrderedDict()
    p._manual_offset = 0
    p._groups = []
    p._temp_swaps = {}
    p._weekend_mode = weekend_mode
    p._slot_days = slot_days
    p._merge_pairs = m.Plugin._parse_merge_pairs(merge_pairs or [])
    p._units_memo = OrderedDict()
    return p


# ------------------------------------------------------------ 旧实现（参照）
def ref_is_holiday(p: "m.Plugin", day: date) -> bool:
    """旧版线性扫描。"""
    iso = day.isoformat()
    for h in p._holidays:
        if h.start and h.start <= iso <= (h.end or h.start):
            return True
    return False


def ref_compute(p: "m.Plugin", start: date, today: date) -> int:
    """旧版逐日实现（优化前的代码 + 周末处理扩展），作为差分参照。"""
    mode = p._rotation_mode
    days = (today - start).days
    if days <= 0:
        return 0

    if mode == m.MODE_DAILY:
        return sum(
            1
            for k in range(1, days + 1)
            if not ref_is_holiday(p, start + timedelta(days=k))
        )

    if mode == m.MODE_WEEKLY:
        slots = 0
        block_start = start + timedelta(days=7)
        while block_start <= today:
            if any(
                not ref_is_holiday(p, block_start + timedelta(days=n))
                for n in range(7)
            ):
                slots += 1
            block_start += timedelta(days=7)
        return slots

    # workday：each=周末逐日计档（等价每天轮换）；skip=周末不计；merge=旧逻辑
    if p._weekend_mode == m.WEEKEND_EACH:
        return sum(
            1
            for k in range(1, days + 1)
            if not ref_is_holiday(p, start + timedelta(days=k))
        )

    slots = 0
    count_weekend = p._weekend_mode != m.WEEKEND_SKIP
    cur = start + timedelta(days=1)
    while cur <= today:
        wd = cur.weekday()
        if wd < 5:
            if not ref_is_holiday(p, cur):
                slots += 1
        elif count_weekend:
            if wd == 5:
                sunday = cur + timedelta(days=1)
                if not ref_is_holiday(p, cur) or (
                    sunday <= today and not ref_is_holiday(p, sunday)
                ):
                    slots += 1
            else:
                saturday = cur - timedelta(days=1)
                if saturday < start and not ref_is_holiday(p, cur):
                    slots += 1
        cur += timedelta(days=1)
    return slots


# ------------------------------------------------------------ 用例
PASS = 0
FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got={got} want={want}")


def test_manual_cases() -> None:
    # weekly：无假期时 14 天 = 2 档
    p = make_plugin(m.MODE_WEEKLY, "2026-01-01", [])
    check("weekly 无假期 14天",
          p._compute_elapsed_slots(date(2026, 1, 1), date(2026, 1, 15)), 2)

    # weekly：第 1 个完整周（01-08~01-14）全是假期 -> 该周跳过
    p = make_plugin(m.MODE_WEEKLY, "2026-01-01", [
        {"start": "2026-01-08", "end": "2026-01-14", "name": "寒假"},
    ])
    check("weekly 整周假期跳过",
          p._compute_elapsed_slots(date(2026, 1, 1), date(2026, 1, 15)), 1)

    # weekly：相邻两段假期拼出整周覆盖（合并区间语义）
    p = make_plugin(m.MODE_WEEKLY, "2026-01-01", [
        {"start": "2026-01-08", "end": "2026-01-11", "name": "甲"},
        {"start": "2026-01-12", "end": "2026-01-14", "name": "乙"},
    ])
    check("weekly 相邻假期合并覆盖整周",
          p._compute_elapsed_slots(date(2026, 1, 1), date(2026, 1, 15)), 1)

    # daily：3 天中 1 天假期
    p = make_plugin(m.MODE_DAILY, "2026-01-01", [
        {"start": "2026-01-02", "end": "2026-01-02", "name": ""},
    ])
    check("daily 1 天假期",
          p._compute_elapsed_slots(date(2026, 1, 1), date(2026, 1, 4)), 2)

    # daily：假期窗口外（起始日之前）不计
    p = make_plugin(m.MODE_DAILY, "2026-01-10", [
        {"start": "2026-01-01", "end": "2026-01-05", "name": ""},
    ])
    check("daily 窗口外假期",
          p._compute_elapsed_slots(date(2026, 1, 10), date(2026, 1, 13)), 3)

    # workday：起始日 2026-01-03 为周六
    # 01-04 周日不计（cur == start+1）；01-05~09 五天；01-10 周六 +1；
    # 01-11 周日（周六非假期，不计） -> 共 6
    p = make_plugin(m.MODE_WORKDAY, "2026-01-03", [])
    check("workday 起始日周六",
          p._compute_elapsed_slots(date(2026, 1, 3), date(2026, 1, 11)), 6)

    # workday：周六假期、周日自由 -> 周日补 1 档
    p = make_plugin(m.MODE_WORKDAY, "2026-01-05", [
        {"start": "2026-01-10", "end": "2026-01-10", "name": "调休"},
    ])
    check("workday 周六假期周日补档",
          p._compute_elapsed_slots(date(2026, 1, 5), date(2026, 1, 12)), 6)

    # workday：整个周末都是假期 -> 周末档不计
    p = make_plugin(m.MODE_WORKDAY, "2026-01-05", [
        {"start": "2026-01-10", "end": "2026-01-11", "name": "调休"},
    ])
    check("workday 周末全假期",
          p._compute_elapsed_slots(date(2026, 1, 5), date(2026, 1, 12)), 5)

    # 边界：today <= start
    check("today <= start",
          p._compute_elapsed_slots(date(2026, 1, 5), date(2026, 1, 5)), 0)

    # weekly：长跨度 52 周，公式 O(H) 结果与逐周一致
    p = make_plugin(m.MODE_WEEKLY, "2025-09-01", [
        {"start": "2026-07-01", "end": "2026-08-31", "name": "暑假"},
    ])
    s, t = date(2025, 9, 1), date(2026, 9, 1)
    check("weekly 长跨度暑假",
          p._compute_elapsed_slots(s, t), ref_compute(p, s, t))


def test_random_differential(n: int = 2000, seed: int = 42) -> None:
    """随机场景：优化后实现 vs 旧逐日实现。"""
    rng = random.Random(seed)
    base = date(2025, 1, 1)
    for i in range(n):
        start = base + timedelta(days=rng.randint(0, 700))
        today = start + timedelta(days=rng.randint(0, 900))
        mode = rng.choice(m.VALID_MODES)
        wm = rng.choice(m.VALID_WEEKEND_MODES) if mode == m.MODE_WORKDAY else "merge"
        holidays = []
        for _ in range(rng.randint(0, 8)):
            hs = base + timedelta(days=rng.randint(-30, 1600))
            he = hs + timedelta(days=rng.randint(0, rng.choice([0, 1, 3, 10, 62])))
            if rng.random() < 0.2:
                hs, he = he, hs  # 逆序（解析时会交换）
            holidays.append({"start": hs.isoformat(), "end": he.isoformat(),
                             "name": ""})
        p = make_plugin(mode, start.isoformat(), holidays, wm)
        check(f"rand#{i} {mode}/{wm}",
              p._compute_elapsed_slots(start, today),
              ref_compute(p, start, today))


def test_holiday_lookup_equiv(seed: int = 7) -> None:
    """_is_holiday / _find_holiday 与线性扫描等价。"""
    rng = random.Random(seed)
    holidays = [
        {"start": "2026-01-05", "end": "2026-01-09", "name": "A"},
        {"start": "2026-01-08", "end": "2026-01-12", "name": "B"},  # 与 A 重叠
        {"start": "2026-03-01", "end": "2026-03-01", "name": "单日"},
        {"start": "2026-07-01", "end": "2026-08-31", "name": "暑假"},
    ]
    p = make_plugin(m.MODE_WEEKLY, "2025-09-01", holidays)
    base = date(2025, 12, 1)
    for i in range(500):
        day = base + timedelta(days=rng.randint(0, 400))
        check(f"is_holiday#{i} {day}", p._is_holiday(day), ref_is_holiday(p, day))
        # _find_holiday 保持“列表序首个覆盖”语义
        want = None
        iso = day.isoformat()
        for h in p._holidays:
            if h.start and h.start <= iso <= (h.end or h.start):
                want = h
                break
        check(f"find_holiday#{i} {day}", p._find_holiday(day), want)


def test_cache_invalidation() -> None:
    """假期变化后 _invalidate_holiday_cache 使二分索引重建。"""
    p = make_plugin(m.MODE_DAILY, "2026-01-01", [])
    s, t = date(2026, 1, 1), date(2026, 1, 11)
    before = p._elapsed_slots(t)
    check("cache 初始", before, 10)
    check("cache 命中一致", p._elapsed_slots(t), before)

    p._holidays = m.Plugin._parse_holidays([
        {"start": "2026-01-02", "end": "2026-01-06", "name": ""},
    ])
    p._slots_cache.clear()
    p._invalidate_holiday_cache()
    check("假期变化后重算", p._elapsed_slots(t), 5)


def test_slot_days() -> None:
    """轮换步长：每 N 个单位算一次值日；假期不占步长，档内进度正确。"""
    # daily + 步长 2：01-01 起，第 1~2 天为第 1 次，第 3~4 天为第 2 次
    p = make_plugin(m.MODE_DAILY, "2026-01-01", [], slot_days=2)
    for day, want in [
        (date(2026, 1, 1), 0), (date(2026, 1, 2), 0),
        (date(2026, 1, 3), 1), (date(2026, 1, 4), 1),
        (date(2026, 1, 5), 2), (date(2026, 1, 9), 4),
    ]:
        check(f"daily 步长2 {day}", p._elapsed_slots(day), want)
    check("daily 步长2 档内进度",
          [p._slot_progress(date(2026, 1, d)) for d in (1, 2, 3, 4, 5)],
          [(1, 2), (2, 2), (1, 2), (2, 2), (1, 2)])

    # 假期不推进轮换：01-03 假期 -> 01-02/01-04 才算满 2 个单位
    p = make_plugin(m.MODE_DAILY, "2026-01-01", [
        {"start": "2026-01-03", "end": "2026-01-03", "name": ""},
    ], slot_days=2)
    check("daily 步长2 跳过假期", p._elapsed_slots(date(2026, 1, 4)), 1)
    # 01-02 为本档第 2 个单位；01-03 假期不占位；01-04 进入下一档的第 1 个单位
    check("daily 步长2 假期后进度", p._slot_progress(date(2026, 1, 4)), (1, 2))

    # weekly + 步长 2：每两周换一次
    p = make_plugin(m.MODE_WEEKLY, "2026-01-01", [], slot_days=2)
    check("weekly 步长2 第1周", p._elapsed_slots(date(2026, 1, 8)), 0)
    check("weekly 步长2 第3周", p._elapsed_slots(date(2026, 1, 22)), 1)
    check("weekly 步长2 第5周", p._elapsed_slots(date(2026, 2, 5)), 2)

    # workday + 步长 2（周末合并计 1 档）：01-05 起，周一~周五 5 档 + 周六 1 档
    p = make_plugin(m.MODE_WORKDAY, "2026-01-05", [], slot_days=2)
    check("workday 步长2 到周日", p._elapsed_slots(date(2026, 1, 11)), 2)
    check("workday 步长2 到下周一", p._elapsed_slots(date(2026, 1, 12)), 3)

    # 步长 1 与旧行为完全一致（随机差分已覆盖，这里抽查两个点）
    p1 = make_plugin(m.MODE_DAILY, "2026-01-01", [], slot_days=1)
    p3 = make_plugin(m.MODE_DAILY, "2026-01-01", [], slot_days=3)
    check("步长1 等于原始档数",
          p1._elapsed_slots(date(2026, 1, 10)),
          p1._compute_elapsed_slots(date(2026, 1, 1), date(2026, 1, 10)))
    check("步长3 三倍跨度",
          p3._elapsed_slots(date(2026, 1, 10)),
          p1._compute_elapsed_slots(date(2026, 1, 1), date(2026, 1, 10)) // 3)

    # 缓存：步长变化后同一天的结果必须失效重算
    p = make_plugin(m.MODE_DAILY, "2026-01-01", [], slot_days=1)
    check("缓存 步长1", p._elapsed_slots(date(2026, 1, 10)), 9)
    p._slot_days = 2
    check("缓存 步长2 重算", p._elapsed_slots(date(2026, 1, 10)), 4)

    # 归一化：脏值/越界回退
    check("clamp None", m.Plugin._clamp_slot_days(None), 1)
    check("clamp 空串", m.Plugin._clamp_slot_days(""), 1)
    check("clamp 非法", m.Plugin._clamp_slot_days("abc"), 1)
    check("clamp 下界", m.Plugin._clamp_slot_days(0), 1)
    check("clamp 上界", m.Plugin._clamp_slot_days(999), m.SLOT_DAYS_MAX)
    check("clamp 字符串数字", m.Plugin._clamp_slot_days("2"), 2)


def test_merge_pairs() -> None:
    """临时合并：任意两天绑定为一对，合计 1 档。"""
    # 起始 03-02，第 1 天不计档：03-03..03-06 原本各计 1 档
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [])
    check("合并前 03-06", p._elapsed_slots(date(2026, 3, 6)), 4)

    # 相邻两天 03-03 + 03-04 → 合计 1 档
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [], merge_pairs=[("2026-03-03", "2026-03-04")])
    check("相邻对 03-04", p._elapsed_slots(date(2026, 3, 4)), 1)
    check("相邻对 03-06", p._elapsed_slots(date(2026, 3, 6)), 3)

    # 任意（不相邻）两天 03-03 + 03-06：03-06 当天才折算，之前不受影响
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [], merge_pairs=[("2026-03-06", "2026-03-03")])
    check("跨日对 03-05 未折算", p._elapsed_slots(date(2026, 3, 5)), 3)
    check("跨日对 03-06 折算", p._elapsed_slots(date(2026, 3, 6)), 3)
    check("跨日对 03-08 折算", p._elapsed_slots(date(2026, 3, 8)), 5)

    # 起始日自身不计档，与起始日配对不会额外扣减
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [], merge_pairs=[("2026-03-02", "2026-03-03")])
    check("含起始日无扣减", p._elapsed_slots(date(2026, 3, 4)), 2)

    # 一端是假期 → 无从合并，不扣减
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [
        {"start": "2026-03-04", "end": "2026-03-04", "name": ""},
    ], merge_pairs=[("2026-03-03", "2026-03-04")])
    check("一端假期不合并", p._elapsed_slots(date(2026, 3, 6)), 3)

    # 两对独立：各扣 1 档
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [], merge_pairs=[
        ("2026-03-03", "2026-03-04"), ("2026-03-05", "2026-03-06"),
    ])
    check("两对独立扣两次", p._elapsed_slots(date(2026, 3, 6)), 2)

    # 同一天只属于一对：重叠的配对被丢弃
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [], merge_pairs=[
        ("2026-03-03", "2026-03-04"), ("2026-03-04", "2026-03-05"),
    ])
    check("重叠只留第一对", len(p._merge_pairs), 1)
    check("重叠对档数", p._elapsed_slots(date(2026, 3, 5)), 2)

    # 工作日轮换：周二 + 周四合并（中间隔着周三）
    p = make_plugin(m.MODE_WORKDAY, "2026-03-02", [], merge_pairs=[("2026-03-03", "2026-03-05")])
    check("workday 合并前 03-07",
          make_plugin(m.MODE_WORKDAY, "2026-03-02", [])._elapsed_slots(date(2026, 3, 7)), 5)
    check("workday 跨日合并", p._elapsed_slots(date(2026, 3, 7)), 4)

    # 工作日轮换：周日不计档（周六已代表周末），与周日配对无效
    p = make_plugin(m.MODE_WORKDAY, "2026-03-02", [], merge_pairs=[("2026-03-03", "2026-03-08")])
    check("workday 周日端无效", p._elapsed_slots(date(2026, 3, 9)), 6)

    # 每周轮换：计档单位是周，只有周界日能配对
    p = make_plugin(m.MODE_WEEKLY, "2026-03-02", [], merge_pairs=[("2026-03-03", "2026-03-04")])
    check("weekly 非周界无效", p._elapsed_slots(date(2026, 3, 23)), 3)
    p = make_plugin(m.MODE_WEEKLY, "2026-03-02", [], merge_pairs=[("2026-03-09", "2026-03-16")])
    check("weekly 周界可合并", p._elapsed_slots(date(2026, 3, 23)), 2)

    # 与步长叠加：先扣合并再除步长
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [], slot_days=2,
                    merge_pairs=[("2026-03-03", "2026-03-04")])
    check("合并 + 步长2", p._elapsed_slots(date(2026, 3, 6)), 1)

    # 配对双方互查
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [], merge_pairs=[("2026-03-03", "2026-03-06")])
    check("partner A→B", p._merge_partner(date(2026, 3, 3)), "2026-03-06")
    check("partner B→A", p._merge_partner(date(2026, 3, 6)), "2026-03-03")
    check("partner 无关日", p._merge_partner(date(2026, 3, 5)), "")

    # add_merge_pair / remove_merge_pair
    p = make_plugin(m.MODE_DAILY, "2026-03-02", [])
    p._persist = lambda: None
    check("add 非法格式", m.Plugin.add_merge_pair(p, "2026-3-2", "2026-03-03"), False)
    check("add 不存在日期", m.Plugin.add_merge_pair(p, "2026-13-01", "2026-03-03"), False)
    check("add 同一天", m.Plugin.add_merge_pair(p, "2026-03-03", "2026-03-03"), False)
    check("add 建立配对", m.Plugin.add_merge_pair(p, "2026-03-03", "2026-03-06"), True)
    check("add 后列表", p._merge_pairs, [("2026-03-03", "2026-03-06")])
    check("add 幂等", m.Plugin.add_merge_pair(p, "2026-03-06", "2026-03-03"), True)
    check("add 幂等后一条", len(p._merge_pairs), 1)
    check("add 顶掉旧配对", m.Plugin.add_merge_pair(p, "2026-03-06", "2026-03-08"), True)
    check("add 顶掉后列表", p._merge_pairs, [("2026-03-06", "2026-03-08")])
    check("get 返回字典", m.Plugin.get_merge_pairs(p),
          [{"a": "2026-03-06", "b": "2026-03-08"}])
    check("remove 已有", m.Plugin.remove_merge_pair(p, "2026-03-06"), True)
    check("remove 后清空", p._merge_pairs, [])
    check("remove 不存在", m.Plugin.remove_merge_pair(p, "2026-03-09"), True)
    check("remove 非法", m.Plugin.remove_merge_pair(p, "bad"), False)

    # _parse_merge_pairs 归一化：排序、去重、丢非法、拒重叠
    check("parse 排序", m.Plugin._parse_merge_pairs([{"a": "2026-03-06", "b": "2026-03-03"}]),
          [("2026-03-03", "2026-03-06")])
    check("parse 列表写法", m.Plugin._parse_merge_pairs([["2026-03-06", "2026-03-03"]]),
          [("2026-03-03", "2026-03-06")])
    check("parse 去重", m.Plugin._parse_merge_pairs(
        [("2026-03-03", "2026-03-04"), ("2026-03-03", "2026-03-04")]),
        [("2026-03-03", "2026-03-04")])
    check("parse 丢非法", m.Plugin._parse_merge_pairs(
        ["x", None, ("2026-13-01", "2026-03-03"), ("2026-03-03", "2026-03-03")]), [])
    # 区间可以交叠，只要不共享同一天
    check("parse 允许区间交叠", m.Plugin._parse_merge_pairs(
        [("2026-03-03", "2026-03-06"), ("2026-03-05", "2026-03-09")]),
        [("2026-03-03", "2026-03-06"), ("2026-03-05", "2026-03-09")])
    # 共享同一天则后一对被拒
    check("parse 拒共享日", m.Plugin._parse_merge_pairs(
        [("2026-03-03", "2026-03-06"), ("2026-03-06", "2026-03-09")]),
        [("2026-03-03", "2026-03-06")])
    check("parse 非列表", m.Plugin._parse_merge_pairs("2026-03-03"), [])

    # 旧版「与次日合并」数据仍在解析范围内（迁移的原料）
    check("legacy 解析", m.Plugin._parse_merge_days(["2026-03-05", "2026-03-03"]),
          ["2026-03-03", "2026-03-05"])
    check("legacy 丢非法", m.Plugin._parse_merge_days(["x", None, "2026-13-01"]), [])


def main() -> int:
    test_manual_cases()
    test_holiday_lookup_equiv()
    test_cache_invalidation()
    test_slot_days()
    test_merge_pairs()
    test_random_differential()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
