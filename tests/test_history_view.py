# -*- coding: utf-8 -*-
"""历史记录浏览页数据（get_history_overview / get_history_month）回归测试。

运行方式（无需 CW2 环境）：
    python tests/test_history_view.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_robustness as rb  # noqa: E402

m = rb.m
Plugin = m.Plugin
make_plugin = rb.make_plugin

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got={got!r} want={want!r}")


def rec(day, group, auto="", absent=(), profile="pa", total=2):
    return {
        "date": day,
        "group_name": group,
        "auto_group_name": auto,
        "members": [
            {"name": f"人{i}", "task": "扫地",
             "status": "absent" if i in absent else "normal"}
            for i in range(total)
        ],
        "profile": profile,
    }


def hist_plugin(records, active="pa"):
    p = make_plugin()
    p._history = records
    p._active_profile_id = active
    return p


def test_overview() -> None:
    check("空历史", Plugin.get_history_overview(make_plugin()),
          {"months": [], "members": [], "total": 0})

    p = hist_plugin([
        rec("2026-10-05", "甲组", absent=(1,)),
        rec("2026-10-06", "乙组"),
        rec("2026-09-28", "甲组"),
        rec("2026-10-07", "丙组", profile="pb"),  # 其他方案不可见
    ])
    d = Plugin.get_history_overview(p)
    check("月份升序去重", d["months"], ["2026-09", "2026-10"])
    check("成员去重排序", d["members"], ["人0", "人1"])
    check("总数限当前方案", d["total"], 3)

    # 脏日期不进月份列表，但仍计入总数（与统计口径一致）
    p = hist_plugin([rec("坏日期", "甲组"), rec("", "甲组"), rec("2026-10-05", "甲组")])
    d = Plugin.get_history_overview(p)
    check("脏日期不进月份", d["months"], ["2026-10"])
    check("脏日期计入总数", d["total"], 3)


def test_month_records() -> None:
    p = hist_plugin([
        rec("2026-10-06", "乙组"),
        rec("2026-10-05", "甲组", auto="甲组", absent=(1,)),
        rec("2026-10-07", "改组", auto="原组"),      # 手动换组 → switched
        rec("2026-10-08", "其他方案", profile="pb"),
        rec("2026-09-30", "上月", auto="上月"),
    ])
    d = Plugin.get_history_month(p, "2026-10")
    rows = d["records"]
    check("按日期升序", [r["date"] for r in rows],
          ["2026-10-05", "2026-10-06", "2026-10-07"])
    check("结构对齐 recent", sorted(rows[0].keys()),
          ["date", "groupName", "members", "switched"])
    check("组名字段", rows[0]["groupName"], "甲组")
    check("成员含状态", rows[0]["members"][1]["status"], "absent")
    check("未换组 switched False", rows[0]["switched"], False)
    check("换组 switched True", rows[2]["switched"], True)
    check("其他方案记录排除", len(rows), 3)


def test_month_dirty_input() -> None:
    p = hist_plugin([rec("2026-10-05", "甲组")])
    for bad in ["", "abc", "2026-13", "2026-10-01", "202610", "2026-00", None]:
        check(f"非法月份 {bad!r}",
              Plugin.get_history_month(p, bad), {"records": []})


def main() -> None:
    test_overview()
    test_month_records()
    test_month_dirty_input()
    print(f"{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
