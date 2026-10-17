# -*- coding: utf-8 -*-
"""多套值日方案（profiles）回归测试。

覆盖：方案解析与装载、旧平铺配置迁移、切换隔离（含缓存失效）、
历史记录按方案隔离、方案增删改约束（最后一个不可删、删除连带删历史）、
备份导出/恢复覆盖全部方案。

运行方式（无需 CW2 环境）：
    python tests/test_profiles.py
"""
import json
import sys
from datetime import date, timedelta
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


def two_profile_plugin():
    """构造甲/乙两方案插件：轮换方式、分组、假期各不相同。"""
    p = make_plugin()
    payload = {
        "active": "pb",
        "profiles": [
            {
                "id": "pa", "name": "单周",
                "groups": [{"name": "甲1组", "members": [{"name": "张三", "task": "扫地"}]}],
                "start_date": "2024-01-01", "rotation_mode": "daily",
                "holidays": [{"start": "2024-02-01", "end": "2024-02-05", "name": "假A"}],
            },
            {
                "id": "pb", "name": "双周",
                "groups": [{"name": "乙1组", "members": [{"name": "李四", "task": "擦黑板"}]}],
                "start_date": "2024-06-01", "rotation_mode": "weekly",
                "holidays": [],
            },
        ],
        "settings": {"font_group": 18},
    }
    Plugin._apply_storage(p, payload)
    return p


def test_parse_profiles() -> None:
    p = make_plugin()
    check("非列表返回空", Plugin._parse_profiles(p, None), [])
    check("空列表返回空", Plugin._parse_profiles(p, []), [])
    # 非 dict 项跳过；dict 项补默认 id/name
    out = Plugin._parse_profiles(p, [1, "x", {}])
    check("跳过非 dict", len(out), 1)
    check("默认名", out[0]["name"], m.DEFAULT_PROFILE_NAME)
    check("补生成 id", len(out[0]["id"]), 12)
    # id 冲突重新生成，保证唯一
    out = Plugin._parse_profiles(
        p, [{"id": "dup", "name": "a"}, {"id": "dup", "name": "b"}]
    )
    check("去重后仍 2 条", len(out), 2)
    check("id 唯一", len({x["id"] for x in out}), 2)
    check("首个保留原 id", out[0]["id"], "dup")
    # name 清洗：空白回退默认、超长截断；settings 键丢弃
    out = Plugin._parse_profiles(
        p, [{"id": "s", "name": "   "}, {"id": "l", "name": "长" * 40},
            {"id": "k", "name": "带设置", "settings": {"font_group": 9}}]
    )
    check("空白名回退默认", out[0]["name"], m.DEFAULT_PROFILE_NAME)
    check("超长名截断 30", len(out[1]["name"]), 30)
    check("settings 不入方案", "settings" in out[2], False)


def test_apply_storage_legacy() -> None:
    """旧平铺格式 → 单个默认方案，行为与 1.12 一致。"""
    p = make_plugin()
    p._settings["font_group"] = 11
    Plugin._apply_storage(p, {
        "groups": [{"name": "甲组", "members": []}],
        "start_date": "2024-03-01",
        "rotation_mode": "daily",
        "settings": {"font_group": 20},
    })
    check("单方案", len(p._profiles), 1)
    check("默认方案名", p._profiles[0]["name"], m.DEFAULT_PROFILE_NAME)
    check("active 指向唯一方案", p._active_profile_id, p._profiles[0]["id"])
    check("分组已应用", p._groups[0].name, "甲组")
    check("轮换已应用", p._rotation_mode, "daily")
    check("settings 已应用", p._settings["font_group"], 20)


def test_apply_storage_profiles() -> None:
    p = two_profile_plugin()
    check("active 取 payload 指定", p._active_profile_id, "pb")
    check("装载乙方案分组", p._groups[0].name, "乙1组")
    check("装载乙方案轮换", p._rotation_mode, "weekly")
    check("起始日期随方案", p._start_date, "2024-06-01")
    check("settings 全局生效", p._settings["font_group"], 18)
    check("方案条目保留", [x["id"] for x in p._profiles], ["pa", "pb"])

    # active 非法 → 回退第一个方案
    p = make_plugin()
    Plugin._apply_storage(p, {
        "active": "不存在",
        "profiles": [{"id": "pa", "name": "甲", "groups": []}],
    })
    check("active 回退首个", p._active_profile_id, "pa")

    # 无 settings 键 → 保留现值
    p = make_plugin()
    p._settings["font_group"] = 21
    Plugin._apply_storage(p, {"profiles": [{"id": "pa", "name": "甲", "groups": []}]})
    check("缺 settings 保留现值", p._settings["font_group"], 21)


def test_storage_roundtrip() -> None:
    p = two_profile_plugin()
    # 运行时改动应同步进 active 方案条目，另一方案条目不动
    p._rotation_mode = "daily"
    payload = Plugin._build_storage_payload(p)
    check("顶层 active", payload["active"], "pb")
    check("顶层 settings", payload["settings"]["font_group"], 18)
    by_id = {x["id"]: x for x in payload["profiles"]}
    check("active 条目同步运行时", by_id["pb"]["rotation_mode"], "daily")
    check("非 active 条目保持原值", by_id["pa"]["rotation_mode"], "daily")
    check("非 active 起始日不变", by_id["pa"]["start_date"], "2024-01-01")
    json.dumps(payload, ensure_ascii=False)  # 必须可序列化
    check("序列化通过", True, True)

    # 与 _apply_storage 往返：再装载得到一致状态
    p2 = make_plugin()
    Plugin._apply_storage(p2, payload)
    check("往返后 active", p2._active_profile_id, "pb")
    check("往返后轮换", p2._rotation_mode, "daily")
    check("往返后 settings", p2._settings["font_group"], 18)


def test_switch_isolation() -> None:
    p = two_profile_plugin()
    p._settings["font_group"] = 18
    p._slots_cache[("x",)] = 1

    check("切到不存在的方案", Plugin.switch_profile(p, "zzz"), False)
    check("切到当前方案为空操作", Plugin.switch_profile(p, "pb"), True)
    check("切到甲方案", Plugin.switch_profile(p, "pa"), True)
    check("分组随方案切换", p._groups[0].name, "甲1组")
    check("轮换随方案切换", p._rotation_mode, "daily")
    check("假期随方案切换", len(p._holidays), 1)
    check("起始日期随方案切换", p._start_date, "2024-01-01")
    check("settings 全局不随切换", p._settings["font_group"], 18)
    check("档位缓存已失效", len(p._slots_cache), 0)
    check("假期缓存已失效", p._holidays_fp, None)
    check("切回乙方案", Plugin.switch_profile(p, "pb"), True)
    check("切回后分组", p._groups[0].name, "乙1组")
    check("切回后假期清空", len(p._holidays), 0)


def test_history_isolation() -> None:
    p = two_profile_plugin()
    today = date.today()
    iso = today.isoformat()

    rec_pb = Plugin._ensure_today_record(p, today, 0, p._groups[0])
    check("pb 方案记录打标", rec_pb["profile"], "pb")
    Plugin.switch_profile(p, "pa")
    rec_pa = Plugin._ensure_today_record(p, today, 0, p._groups[0])
    check("pa 方案记录打标", rec_pa["profile"], "pa")
    check("同一天两方案各一条", len(p._history), 2)

    # 考勤只作用于当前方案
    check("考勤写入成功", Plugin.set_member_status(p, iso, 0, m.STATUS_ABSENT), True)
    pa_rec = next(r for r in p._history if r["profile"] == "pa")
    pb_rec = next(r for r in p._history if r["profile"] == "pb")
    check("当前方案成员已请假", pa_rec["members"][0]["status"], m.STATUS_ABSENT)
    check("另一方案成员不受影响", pb_rec["members"][0]["status"], m.STATUS_NORMAL)

    # 统计只算当前方案
    stats = Plugin.get_stats(p)
    check("统计天数限当前方案", stats["days"], 1)

    # 清空只清当前方案
    Plugin.clear_history(p)
    check("清空后剩另一方案记录", [r["profile"] for r in p._history], ["pb"])

    # 桩实例缺 _active_profile_id 属性时（如 test_stats 的 plugin_with），
    # getattr 兜底为 ""，未打标记录视为当前方案
    p2 = make_plugin()
    del p2._active_profile_id
    p2._history = [{"date": iso, "group_name": "g", "auto_group_name": "",
                    "members": [], "profile": ""}]
    check("旧记录视为当前", len(Plugin._records_for_active(p2)), 1)


def test_delete_profile() -> None:
    # 最后一个方案不可删
    p = make_plugin()
    check("最后一个不可删", Plugin.delete_profile(p, "p0"), False)

    # 删除非 active 方案：其历史连带删除，另一方案保留
    p = two_profile_plugin()
    today = date.today()
    Plugin._ensure_today_record(p, today, 0, p._groups[0])  # pb 的记录
    Plugin.switch_profile(p, "pa")
    Plugin._ensure_today_record(p, today, 0, p._groups[0])  # pa 的记录
    check("删除非 active", Plugin.delete_profile(p, "pb"), True)
    check("方案表更新", [x["id"] for x in p._profiles], ["pa"])
    check("active 不变", p._active_profile_id, "pa")
    check("被删方案历史连带删除", [r["profile"] for r in p._history], ["pa"])

    # 删除 active 方案：自动切到第一个剩余方案并装载
    p = two_profile_plugin()
    check("删除 active", Plugin.delete_profile(p, "pb"), True)
    check("active 自动切换", p._active_profile_id, "pa")
    check("运行时已装载剩余方案", p._groups[0].name, "甲1组")

    # 删除不存在的方案
    p = two_profile_plugin()
    check("删除不存在返回 False", Plugin.delete_profile(p, "zzz"), False)


def test_add_rename_profile() -> None:
    # 复制当前方案
    p = two_profile_plugin()
    p._rotation_mode = "daily"  # 运行时改动先同步再复制
    new_id = Plugin.add_profile(p, "  备用  ", True)
    check("返回新 id", len(new_id), 12)
    check("方案数 +1", len(p._profiles), 3)
    check("自动切换到新方案", p._active_profile_id, new_id)
    check("复制当前分组", p._groups[0].name, "乙1组")
    check("复制当前轮换", p._rotation_mode, "daily")
    entry = next(x for x in p._profiles if x["id"] == new_id)
    check("方案名清洗", entry["name"], "备用")

    # 全新方案：内置示例分组
    fresh_id = Plugin.add_profile(p, "", False)
    entry = next(x for x in p._profiles if x["id"] == fresh_id)
    check("空名自动命名", entry["name"], "方案4")
    check("全新方案用示例分组", p._groups[0]["name"] if isinstance(p._groups[0], dict) else p._groups[0].name, "第1组")

    # 重命名
    check("重命名成功", Plugin.rename_profile(p, new_id, "考试周"), True)
    entry = next(x for x in p._profiles if x["id"] == new_id)
    check("名称已更新", entry["name"], "考试周")
    check("空名拒绝", Plugin.rename_profile(p, new_id, "   "), False)
    check("未知方案拒绝", Plugin.rename_profile(p, "zzz", "名"), False)


def test_get_profiles_payload() -> None:
    p = two_profile_plugin()
    d = Plugin.get_profiles(p)
    check("active 字段", d["active"], "pb")
    check("条目数", len(d["items"]), 2)
    check("条目含 id/name", d["items"][0], {"id": "pa", "name": "单周"})


def test_backup_covers_all_profiles() -> None:
    """备份必须整份带出所有方案，而不只是活动方案。"""
    import tempfile
    from pathlib import Path as _P

    src = two_profile_plugin()
    src._schedule_config_flush = lambda: None
    out = _P(tempfile.gettempdir()) / "duty_backup_profiles.json"
    r = Plugin.export_backup(src, str(out), True, True, True, True)
    check("导出成功", r["ok"], True)

    payload = json.loads(out.read_text(encoding="utf-8"))
    prof = payload["sections"].get("profiles")
    check("备份含 profiles 节", isinstance(prof, dict), True)
    check("profiles 含两个方案", len(prof["items"]), 2)
    check("备份记录了活动方案", prof["active"], "pb")
    names = sorted(p["name"] for p in prof["items"])
    check("两个方案都在", names, ["单周", "双周"])

    # 换到只有单方案的干净实例上恢复，两个方案都应该回来
    dst = make_plugin()
    dst._profiles = [{"id": "px", "name": "旧方案"}]
    dst._active_profile_id = "px"
    dst._schedule_config_flush = lambda: None
    dst._flush_history = lambda: None
    r2 = Plugin.import_backup(dst, str(out.parent / "duty_backup_profiles.json"), True, True, True, True)
    check("恢复成功", r2["ok"], True)
    check("方案数恢复为 2", len(dst._profiles), 2)
    check("活动方案恢复为 pb", dst._active_profile_id, "pb")
    check("提示里说明是方案", "值日方案" in r2["msg"], True)

    # 旧版备份（没有 profiles 节）仍按单方案恢复
    old = {"type": "duty_backup", "version": 1, "sections": {
        "groups": [{"name": "丙组", "members": [{"name": "王五", "task": "拖地"}]}],
    }}
    old_file = _P(tempfile.gettempdir()) / "duty_backup_legacy.json"
    old_file.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    dst2 = make_plugin()
    dst2._schedule_config_flush = lambda: None
    dst2._flush_history = lambda: None
    r3 = Plugin.import_backup(dst2, str(old_file), True, True, True, True)
    check("旧备份仍可恢复", r3["ok"], True)
    check("旧备份恢复的是单方案", len(dst2._groups), 1)
    check("旧备份的组名", dst2._groups[0].name, "丙组")
    old_file.unlink(missing_ok=True)
    out.unlink(missing_ok=True)


def main() -> None:
    test_parse_profiles()
    test_apply_storage_legacy()
    test_apply_storage_profiles()
    test_storage_roundtrip()
    test_switch_isolation()
    test_history_isolation()
    test_delete_profile()
    test_add_rename_profile()
    test_get_profiles_payload()
    test_backup_covers_all_profiles()
    print(f"{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
