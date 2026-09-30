# -*- coding: utf-8 -*-
"""槽函数健壮性测试：极端 / 脏输入不得抛异常。

QML 端在数据未就绪时可能传 undefined，若槽函数直接拿它参与比较会抛
TypeError 并中断调用，表现为「点了没反应 + 控制台报错」。这里对所有
接收外部输入的槽函数灌入一批脏值，要求一律安全返回。

运行：
    python tests/test_robustness.py
"""
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_rotation as t  # noqa: E402

m = t.m

PASS = 0
FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got={got!r} want={want!r}")


class _TimerStub:
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


def make_plugin(groups=None, start: str = "2020-01-01", mode: str = m.MODE_DAILY):
    p = object.__new__(m.Plugin)
    p._groups = groups if groups is not None else [
        m.DutyGroup(name="组1", members=[
            m.DutyMember(name="张三", task="扫地"),
            m.DutyMember(name="李四", task="擦黑板"),
        ]),
        m.DutyGroup(name="组2", members=[]),
    ]
    p._holidays = []
    p._holidays_fp = None
    p._holiday_idx = None
    p._slots_cache = OrderedDict()
    p._units_memo = OrderedDict()
    p._merge_valid = None
    p._merge_index = None
    p._start_date = start
    p._start_day = date.fromisoformat(start)
    p._rotation_mode = mode
    p._weekend_mode = m.WEEKEND_MERGE
    p._slot_days = 1
    p._merge_pairs = []
    p._manual_offset = 0
    p._temp_swaps = {}
    p._task_swaps = {}
    p._settings = dict(m.DEFAULT_SETTINGS)
    p._history = []
    p._history_path = ROOT / "data" / "history.json"
    p._notifier = None
    p._reminder_fired_date = ""
    p._config_timer = _TimerStub()
    p._history_timer = _TimerStub()
    p._persist = lambda: None
    p._emit_duty_changed = lambda: None
    return p


# QML 可能灌进来的脏值：undefined 对应 None，另有空串、越界数、非法日期等
DIRTY = [None, "", "  ", 0, -1, 999999, "2026-13-01", "abc", [], {}, True, 3.7, "2026-03-01"]


def test_no_exception() -> None:
    """所有接收外部输入的槽函数：脏输入一律安全返回，不得抛异常。"""
    global PASS, FAIL
    cases = [
        ("set_temp_swap(day)", lambda p, v: m.Plugin.set_temp_swap(p, v, 0)),
        ("set_temp_swap(idx)", lambda p, v: m.Plugin.set_temp_swap(p, "2026-03-01", v)),
        ("save_slot_days", lambda p, v: m.Plugin.save_slot_days(p, v)),
        ("save_weekend_mode", lambda p, v: m.Plugin.save_weekend_mode(p, v)),
        ("add_merge_pair", lambda p, v: m.Plugin.add_merge_pair(p, v, "2026-03-02")),
        ("add_merge_pair(b)", lambda p, v: m.Plugin.add_merge_pair(p, "2026-03-02", v)),
        ("remove_merge_pair", lambda p, v: m.Plugin.remove_merge_pair(p, v)),
        ("set_member_status(day)", lambda p, v: m.Plugin.set_member_status(p, v, 0, "absent")),
        ("set_member_status(idx)", lambda p, v: m.Plugin.set_member_status(p, "2026-03-01", v, "absent")),
        ("set_member_status(st)", lambda p, v: m.Plugin.set_member_status(p, "2026-03-01", 0, v)),
        ("swap_member_tasks(a)", lambda p, v: m.Plugin.swap_member_tasks(p, v, 1)),
        ("swap_member_tasks(b)", lambda p, v: m.Plugin.swap_member_tasks(p, 0, v)),
        ("set_member_task(idx)", lambda p, v: m.Plugin.set_member_task(p, v, "拖地")),
        ("set_member_task(task)", lambda p, v: m.Plugin.set_member_task(p, 0, v)),
        ("reset_member_task", lambda p, v: m.Plugin.reset_member_task(p, v)),
        ("get_month_info(year)", lambda p, v: m.Plugin.get_month_info(p, v, 3)),
        ("get_month_info(month)", lambda p, v: m.Plugin.get_month_info(p, 2026, v)),
        ("export_schedule(weeks)", lambda p, v: m.Plugin.export_schedule(p, v, "")),
        ("save_holidays", lambda p, v: m.Plugin.save_holidays(p, v)),
        ("save_all(mode)", lambda p, v: m.Plugin.save_all(p, "2020-01-01", v, [])),
        ("save_all(groups)", lambda p, v: m.Plugin.save_all(p, "2020-01-01", "daily", v)),
    ]
    for name, fn in cases:
        for v in DIRTY:
            p = make_plugin()
            try:
                fn(p, v)
                PASS += 1
            except Exception as e:  # noqa: BLE001  正是要捕获所有异常
                FAIL += 1
                print(f"[FAIL] {name}({v!r}) 抛异常: {type(e).__name__}: {e}")


def test_coerce_index() -> None:
    check("coerce int", m.Plugin._coerce_index(3), 3)
    check("coerce 数字字符串", m.Plugin._coerce_index("3"), 3)
    check("coerce None", m.Plugin._coerce_index(None), None)
    check("coerce 空串", m.Plugin._coerce_index(""), None)
    check("coerce 非数字", m.Plugin._coerce_index("abc"), None)
    check("coerce bool", m.Plugin._coerce_index(True), None)
    check("coerce list", m.Plugin._coerce_index([]), None)
    check("coerce 负", m.Plugin._coerce_index(-2), -2)


def test_empty_groups() -> None:
    """无分组时所有槽函数应安全降级，不得因取模/索引崩溃。"""
    p = make_plugin(groups=[])
    check("无分组 set_temp_swap", m.Plugin.set_temp_swap(p, "2026-03-01", 0), False)
    check("无分组 swap", m.Plugin.swap_member_tasks(p, 0, 1), False)
    check("无分组 set_task", m.Plugin.set_member_task(p, 0, "拖地"), False)
    check("无分组 reset", m.Plugin.reset_member_task(p, 0), False)
    check("无分组 clear", m.Plugin.clear_task_swaps(p), True)
    check("无分组 get_task_swaps", m.Plugin.get_task_swaps(p)["active"], False)
    d = m.Plugin.get_today_duty(p)
    check("无分组 groupName", d["groupName"], "未配置")
    check("无分组 members", d["members"], [])


def main() -> int:
    test_coerce_index()
    test_no_exception()
    test_empty_groups()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
