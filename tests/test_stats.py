# -*- coding: utf-8 -*-
"""统计图表数据（get_stats 的 byWeek / byGroup）回归测试。

运行方式（无需 CW2 环境）：
    python tests/test_stats.py
"""

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

_spec = importlib.util.spec_from_file_location(
    "_rot", ROOT / "tests" / "test_rotation.py"
)
_rot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rot)

m = _rot.m
Plugin = m.Plugin

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got={got!r} want={want!r}")


def plugin_with(history):
    p = object.__new__(Plugin)
    p._history = history
    return p


def rec(day: str, group: str, auto: str = "", absent: int = 0, total: int = 2):
    return {
        "date": day,
        "group_name": group,
        "auto_group_name": auto or group,
        "members": [
            {"name": f"人{i}", "task": "扫地", "status": "absent" if i < absent else "normal"}
            for i in range(total)
        ],
    }


def test_by_week() -> None:
    p = plugin_with([])
    check("空历史 byWeek", p._stats_by_week([]), [])
    check("空历史 byGroup", p._stats_by_group([]), [])

    # 2026-10-05 是周一，往前一周是 09-28
    hist = [
        rec("2026-10-05", "甲组"),
        rec("2026-10-06", "甲组", absent=1),
        rec("2026-10-07", "乙组"),
        rec("2026-09-29", "甲组", absent=2),
    ]
    p = plugin_with(hist)
    weeks = p._stats_by_week(hist)
    check("周数", len(weeks), 2)
    check("按周一日期升序", [w["label"] for w in weeks], ["9/28", "10/5"])
    check("本周天数", weeks[1]["count"], 3)
    check("本周请假人次", weeks[1]["absent"], 1)
    check("上周天数", weeks[0]["count"], 1)
    check("上周请假人次", weeks[0]["absent"], 2)

    # 只保留最近 STATS_WEEKS_LIMIT 周
    many = [rec((date(2026, 1, 5) + timedelta(days=7 * k)).isoformat(), "甲组")
            for k in range(20)]
    p = plugin_with(many)
    check("周数上限", len(p._stats_by_week(many)), Plugin.STATS_WEEKS_LIMIT)
    check("保留的是最近 12 周", p._stats_by_week(many)[-1]["label"], "5/18")


def test_by_group() -> None:
    hist = [
        rec("2026-10-05", "乙组", absent=1),
        rec("2026-10-06", "甲组"),
        rec("2026-10-07", "乙组"),
        rec("2026-10-08", "丙组", absent=2),
        rec("2026-10-09", ""),
    ]
    p = plugin_with(hist)
    groups = p._stats_by_group(hist)
    check("按次数降序", [g["name"] for g in groups], ["乙组", "丙组", "甲组", "（未命名组）"])
    check("乙组天数", groups[0]["count"], 2)
    check("乙组请假", groups[0]["absent"], 1)
    check("丙组请假", groups[1]["absent"], 2)
    check("甲组请假", groups[2]["absent"], 0)


def test_dirty_input() -> None:
    # 脏日期 / 缺字段 / 成员为空都不能让图表崩
    hist = [
        {"date": "坏日期", "group_name": "甲组", "members": []},
        {"date": "", "group_name": "甲组", "members": []},
        {"date": "2026-10-05", "members": []},
        {"date": "2026-10-06", "group_name": "甲组", "members": []},
    ]
    p = plugin_with(hist)
    check("脏日期不进周图", len(p._stats_by_week(hist)), 1)
    check("同周两天合并计数", p._stats_by_week(hist)[0]["count"], 2)
    names = [g["name"] for g in p._stats_by_group(hist)]
    check("无组名归到未命名", "（未命名组）" in names, True)
    check("无成员时请假为 0",
          [g for g in p._stats_by_group(hist) if g["name"] == "（未命名组）"][0]["absent"], 0)


def test_absent_counting() -> None:
    # 无姓名的请假记录不计入人次（与按人统计口径一致）
    hist = [{
        "date": "2026-10-05", "group_name": "甲组", "auto_group_name": "甲组",
        "members": [
            {"name": "", "task": "扫地", "status": "absent"},
            {"name": "张三", "task": "扫地", "status": "absent"},
            {"name": "李四", "task": "扫地", "status": "normal"},
        ],
    }]
    p = plugin_with(hist)
    check("只算有姓名的请假", p._record_absent(hist[0]), 1)
    check("周图口径一致", p._stats_by_week(hist)[0]["absent"], 1)
    check("分组口径一致", p._stats_by_group(hist)[0]["absent"], 1)


def test_get_stats_payload() -> None:
    """get_stats 必须带上图表字段，供 QML 直接绑定。"""
    p = plugin_with([rec("2026-10-05", "甲组"), rec("2026-10-06", "乙组", absent=1)])
    d = Plugin.get_stats(p)
    for key in ("days", "rows", "recent", "byWeek", "byGroup"):
        check(f"含字段 {key}", key in d, True)
    check("byWeek 条数", len(d["byWeek"]), 1)
    check("byGroup 条数", len(d["byGroup"]), 2)


def main() -> int:
    test_by_week()
    test_by_group()
    test_dirty_input()
    test_absent_counting()
    test_get_stats_payload()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())