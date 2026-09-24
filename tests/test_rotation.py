# -*- coding: utf-8 -*-
"""轮换引擎回归测试：优化后 _compute_elapsed_slots 与旧逐日实现差分等价。

运行方式（无需 CW2 环境，桩掉 ClassWidgets.SDK / PySide6.QtCore 即可）：
    python tests/test_rotation.py

覆盖：
  1. 手工核算用例（整周假期、周末合并、起始日为周六等边界）
  2. 随机差分（优化后公式实现 vs 内嵌旧逐日实现，2000 组随机场景）
  3. _is_holiday / _find_holiday 与线性扫描的等价性
  4. 缓存失效（假期变化后 _invalidate_holiday_cache 生效）
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


def make_plugin(mode: str, start: str, holidays: list) -> "m.Plugin":
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
    """旧版逐日实现（优化前的代码），作为差分参照。"""
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

    # workday
    slots = 0
    cur = start + timedelta(days=1)
    while cur <= today:
        wd = cur.weekday()
        if wd < 5:
            if not ref_is_holiday(p, cur):
                slots += 1
        elif wd == 5:
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
        holidays = []
        for _ in range(rng.randint(0, 8)):
            hs = base + timedelta(days=rng.randint(-30, 1600))
            he = hs + timedelta(days=rng.randint(0, rng.choice([0, 1, 3, 10, 62])))
            if rng.random() < 0.2:
                hs, he = he, hs  # 逆序（解析时会交换）
            holidays.append({"start": hs.isoformat(), "end": he.isoformat(),
                             "name": ""})
        p = make_plugin(mode, start.isoformat(), holidays)
        check(f"rand#{i} {mode}",
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


def main() -> int:
    test_manual_cases()
    test_holiday_lookup_equiv()
    test_cache_invalidation()
    test_random_differential()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
