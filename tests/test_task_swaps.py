# -*- coding: utf-8 -*-
"""临时任务调整（当轮有效）回归测试。

复用 tests/test_rotation.py 的桩（ClassWidgets.SDK / PySide6.QtCore），
覆盖：互换、单改、恢复、越界拒绝、换档/换组失效、持久化往返、脏值归一化。

运行：
    python tests/test_task_swaps.py
"""
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_rotation as t  # noqa: E402  导入即安装桩并 import main

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


def make_plugin(names_tasks, start: str = "2020-01-01", mode: str = m.MODE_DAILY):
    """构造带分组的 Plugin：names_tasks = [[(姓名, 任务), ...], ...]"""
    p = object.__new__(m.Plugin)
    p._groups = [
        m.DutyGroup(
            name=f"第{i + 1}组",
            members=[m.DutyMember(name=n, task=k) for n, k in members],
        )
        for i, members in enumerate(names_tasks)
    ]
    p._holidays = []
    p._holidays_fp = None
    p._holiday_idx = None
    p._slots_cache = OrderedDict()
    p._units_memo = OrderedDict()
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


def today_tasks(p):
    d = m.Plugin.get_today_duty(p)
    return d["taskSwapActive"], [x["task"] for x in d["members"]], [
        (x["task"], x["origTask"], x["swapped"]) for x in d["members"]
    ]


def test_basic() -> None:
    p = make_plugin([[("张三", "扫地"), ("李四", "擦黑板"), ("王五", "倒垃圾")],
                     [("赵六", "拖地")]])

    # 无调整时：任务即原始任务，swapped 全 False
    active, tasks, rows = today_tasks(p)
    check("初始未生效", active, False)
    check("初始任务", tasks, ["扫地", "擦黑板", "倒垃圾"])
    check("初始 swapped", [r[2] for r in rows], [False, False, False])
    check("origTask 保留", [r[1] for r in rows], ["扫地", "擦黑板", "倒垃圾"])

    # 互换 0 与 1
    check("互换成功", m.Plugin.swap_member_tasks(p, 0, 1), True)
    active, tasks, rows = today_tasks(p)
    check("互换后生效", active, True)
    check("互换后任务", tasks, ["擦黑板", "扫地", "倒垃圾"])
    check("互换后 origTask 不变", [r[1] for r in rows], ["扫地", "擦黑板", "倒垃圾"])
    check("互换后 swapped", [r[2] for r in rows], [True, True, False])

    # 再互换一次应回到原样（基于原始任务对调，非基于当前值）
    m.Plugin.swap_member_tasks(p, 0, 1)
    check("二次互换还原", today_tasks(p)[1], ["扫地", "擦黑板", "倒垃圾"])

    # 与自身互换无效
    check("自互换无效", m.Plugin.swap_member_tasks(p, 1, 1), False)


def test_set_and_reset() -> None:
    p = make_plugin([[("张三", "扫地"), ("李四", "擦黑板")]])
    check("改任务成功", m.Plugin.set_member_task(p, 0, "拖地"), True)
    check("改后任务", today_tasks(p)[1], ["拖地", "擦黑板"])

    # 空串 = 恢复，且全部恢复后记录清空
    check("空串恢复", m.Plugin.set_member_task(p, 0, ""), True)
    check("恢复后任务", today_tasks(p)[1], ["扫地", "擦黑板"])
    check("恢复后记录清空", p._task_swaps, {})

    check("reset 等价", m.Plugin.set_member_task(p, 1, "倒垃圾"), True)
    check("reset 成功", m.Plugin.reset_member_task(p, 1), True)
    check("reset 后任务", today_tasks(p)[1], ["扫地", "擦黑板"])

    # 空白字符串视为恢复
    m.Plugin.set_member_task(p, 0, "  ")
    check("空白视为恢复", p._task_swaps, {})


def test_bounds() -> None:
    p = make_plugin([[("张三", "扫地"), ("李四", "擦黑板")]])
    check("改任务下标越界", m.Plugin.set_member_task(p, 2, "拖地"), False)
    check("改任务负下标", m.Plugin.set_member_task(p, -1, "拖地"), False)
    check("互换下标越界", m.Plugin.swap_member_tasks(p, 0, 5), False)
    check("互换负下标", m.Plugin.swap_member_tasks(p, -1, 0), False)
    check("越界后仍无记录", p._task_swaps, {})

    # 无分组时全部拒绝
    empty = object.__new__(m.Plugin)
    empty._groups = []
    empty._task_swaps = {}
    empty._slots_cache = OrderedDict()
    empty._units_memo = OrderedDict()
    empty._start_date = "2020-01-01"
    empty._start_day = date(2020, 1, 1)
    empty._rotation_mode = m.MODE_DAILY
    empty._holidays = []
    empty._holidays_fp = None
    empty._holiday_idx = None
    empty._manual_offset = 0
    empty._temp_swaps = {}
    empty._slot_days = 1
    empty._merge_pairs = []
    empty._weekend_mode = m.WEEKEND_MERGE
    check("无分组改任务", m.Plugin.set_member_task(empty, 0, "拖地"), False)
    check("无分组互换", m.Plugin.swap_member_tasks(empty, 0, 1), False)


def test_expiry() -> None:
    p = make_plugin([[("张三", "扫地"), ("李四", "擦黑板")]])
    m.Plugin.swap_member_tasks(p, 0, 1)
    check("建立后生效", today_tasks(p)[0], True)

    # 轮到下一档：slot 不一致 → 失效
    p._task_swaps["slot"] = p._task_swaps["slot"] + 1
    check("换档后失效", today_tasks(p)[0], False)
    check("换档后任务还原", today_tasks(p)[1], ["扫地", "擦黑板"])

    # 换组：groupIndex 不一致 → 失效
    m.Plugin.swap_member_tasks(p, 0, 1)
    p._task_swaps["groupIndex"] = p._task_swaps["groupIndex"] + 1
    check("换组后失效", today_tasks(p)[0], False)

    # 成员下标越界的记录被过滤
    m.Plugin.swap_member_tasks(p, 0, 1)
    p._task_swaps["tasks"][7] = "不存在的成员"
    check("越界下标被过滤", today_tasks(p)[1], ["擦黑板", "扫地"])


def test_clear() -> None:
    p = make_plugin([[("张三", "扫地"), ("李四", "擦黑板")]])
    m.Plugin.swap_member_tasks(p, 0, 1)
    m.Plugin.set_member_task(p, 0, "拖地")
    check("清空前生效", today_tasks(p)[0], True)
    check("全部恢复", m.Plugin.clear_task_swaps(p), True)
    check("清空后失效", today_tasks(p)[0], False)
    check("清空后任务", today_tasks(p)[1], ["扫地", "擦黑板"])
    check("空表再清也成功", m.Plugin.clear_task_swaps(p), True)

    # get_task_swaps 的返回结构
    info = m.Plugin.get_task_swaps(p)
    check("get 未生效 active", info["active"], False)
    m.Plugin.set_member_task(p, 0, "拖地")
    info = m.Plugin.get_task_swaps(p)
    check("get 生效 active", info["active"], True)
    check("get tasks", info["tasks"], {"0": "拖地"})


def test_persistence() -> None:
    p = make_plugin([[("张三", "扫地"), ("李四", "擦黑板")]])
    m.Plugin.swap_member_tasks(p, 0, 1)

    payload = p._task_swaps_payload()
    check("payload slot", payload["slot"], p._task_swaps["slot"])
    check("payload groupIndex", payload["groupIndex"], p._task_swaps["groupIndex"])
    check("payload tasks 键为字符串", sorted(payload["tasks"].keys()), ["0", "1"])

    # 往返：重新解析后仍是同一份生效数据
    restored = m.Plugin._parse_task_swaps(payload)
    check("往返 slot", restored["slot"], p._task_swaps["slot"])
    check("往返 tasks", restored["tasks"], p._task_swaps["tasks"])

    # 空记录序列化为空 dict
    p._task_swaps = {}
    check("空记录 payload", p._task_swaps_payload(), {})

    # 完整配置里含 task_swaps
    m.Plugin.swap_member_tasks(p, 0, 1)
    check("配置含 task_swaps", "task_swaps" in p._build_config_payload(), True)


def test_parse_dirty() -> None:
    check("parse None", m.Plugin._parse_task_swaps(None), {})
    check("parse 字符串", m.Plugin._parse_task_swaps("x"), {})
    check("parse 空 dict", m.Plugin._parse_task_swaps({}), {})
    check("parse 缺 tasks", m.Plugin._parse_task_swaps({"slot": 1, "groupIndex": 0}), {})
    check("parse tasks 非 dict",
          m.Plugin._parse_task_swaps({"slot": 1, "groupIndex": 0, "tasks": []}), {})
    check("parse slot 非数字",
          m.Plugin._parse_task_swaps({"slot": "x", "groupIndex": 0, "tasks": {}}), {})
    check("parse 负 slot",
          m.Plugin._parse_task_swaps({"slot": -1, "groupIndex": 0, "tasks": {"0": "a"}}), {})
    check("parse 空 tasks",
          m.Plugin._parse_task_swaps({"slot": 1, "groupIndex": 0, "tasks": {}}), {})
    check("parse 丢弃非法键",
          m.Plugin._parse_task_swaps(
              {"slot": 2, "groupIndex": 1, "tasks": {"0": "扫地", "x": "擦黑板", "-1": "y"}}),
          {"slot": 2, "groupIndex": 1, "tasks": {0: "扫地"}})


def main() -> int:
    test_basic()
    test_set_and_reset()
    test_bounds()
    test_expiry()
    test_clear()
    test_persistence()
    test_parse_dirty()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
