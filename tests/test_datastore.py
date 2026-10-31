# -*- coding: utf-8 -*-
"""升级丢数据 → 自动恢复 的回归测试。

背景：Class Widgets 2 升级插件时走 `configs.json` 的 `pending_operations`，
类型是 `"type": "install"` —— **完全覆盖安装**，整个插件目录会被重建。
插件的私有数据原本写在插件目录内的 `data/` 下，于是每次升级都丢。

修复：DataStore 双写（插件目录 + 插件目录外的备份）+ 启动时自动恢复。

本测试覆盖：
  1. 双写：落盘后两处都有
  2. 覆盖安装（data/ 被删）→ 下次启动自动恢复
  3. 已有数据绝不被备份覆盖
  4. 首次装本版本（外部为空）→ 自动补备份
  5. 备份文件损坏时不拖垮启动
  6. 原子写入：不会留下半截 JSON

运行方式（无需 CW2 环境）：
    python tests/test_datastore.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datastore import BACKUP_FILES, DataStore, backup_dir_for  # noqa: E402

passed = 0
failed = 0


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n       期望 {want!r}\n       实际 {got!r}")


def make_env():
    """造一个 CW2 目录结构：<root>/plugins/<id>/ 与 <root>/configs/。"""
    root = Path(tempfile.mkdtemp(prefix="cw2_store_"))
    plugin_dir = root / "plugins" / "com.test.duty"
    plugin_dir.mkdir(parents=True)
    (root / "configs").mkdir()
    return root, plugin_dir


# --------------------------------------------------------------------- 双写

def test_write_to_both_places():
    print("\n=== ① 双写 ===")
    root, plugin_dir = make_env()
    try:
        store = DataStore(plugin_dir, "com.test.duty")
        store.write_config({"groups": [{"name": "第1组"}]})
        store.write_history([{"date": "2026-01-01", "group_name": "第1组"}])

        check("插件目录有 config.json", (plugin_dir / "data/config.json").exists(), True)
        check("插件目录有 history.json", (plugin_dir / "data/history.json").exists(), True)
        check("外部备份有 config.json",
              (store.backup_dir / "config.json").exists(), True)
        check("外部备份有 history.json",
              (store.backup_dir / "history.json").exists(), True)

        # 内容一致
        a = json.loads((plugin_dir / "data/config.json").read_text(encoding="utf-8"))
        b = json.loads((store.backup_dir / "config.json").read_text(encoding="utf-8"))
        check("两处 config 内容一致", a, b)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------- 升级丢失 → 自动恢复

def test_restore_after_overwrite_install():
    print("\n=== ② 升级覆盖安装后自动恢复 ===")
    root, plugin_dir = make_env()
    try:
        store = DataStore(plugin_dir, "com.test.duty")
        payload = {"groups": [{"name": "第1组", "members": [{"name": "张三"}]}]}
        store.write_config(payload)
        store.write_history([{"date": "2026-01-01"}])

        # 模拟 CW2 升级：整个插件目录被重建，data/ 消失
        shutil.rmtree(plugin_dir)
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "main.py").write_text("# 新版本", encoding="utf-8")
        check("升级后 data/ 确实没了", (plugin_dir / "data").exists(), False)

        # 新插件实例启动 → 应自动恢复
        store2 = DataStore(plugin_dir, "com.test.duty")
        restored = store2.restore_if_missing()
        check("检测到并恢复", sorted(restored), sorted(BACKUP_FILES))
        check("config 已回到插件目录",
              (plugin_dir / "data/config.json").exists(), True)

        got = json.loads((plugin_dir / "data/config.json").read_text(encoding="utf-8"))
        check("恢复的内容与原数据一致", got, payload)

        # 恢复后应当能被读出来
        check("read_config 读到恢复的数据", store2.read_config(), payload)
        check("read_history 读到恢复的数据", store2.read_history(),
              [{"date": "2026-01-01"}])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------- 已有数据不被覆盖

def test_never_overwrite_existing():
    print("\n=== ③ 已有数据绝不被备份覆盖 ===")
    root, plugin_dir = make_env()
    try:
        store = DataStore(plugin_dir, "com.test.duty")
        store.write_config({"version": 1})
        # 外部备份里有一份更新的（比如用户手改过）
        (store.backup_dir / "config.json").write_text(
            json.dumps({"version": 2}), encoding="utf-8")
        # 插件目录的数据是旧的
        (plugin_dir / "data/config.json").write_text(
            json.dumps({"version": 1}), encoding="utf-8")

        restored = store.restore_if_missing()
        check("文件存在时不恢复", restored, [])
        check("插件目录的数据保持原样",
              json.loads((plugin_dir / "data/config.json").read_text(encoding="utf-8")),
              {"version": 1})
    finally:
        shutil.rmtree(root, ignore_errors=True)


# -------------------------------------------------------- 首次装本版本补备份

def test_backup_missing_only():
    print("\n=== ④ 首次装本版本：自动补备份 ===")
    root, plugin_dir = make_env()
    try:
        # 模拟老用户：data/ 里有数据，外部备份目录还是空的
        data = plugin_dir / "data"
        data.mkdir()
        (data / "config.json").write_text(
            json.dumps({"groups": []}), encoding="utf-8")

        store = DataStore(plugin_dir, "com.test.duty")
        copied = store.backup_missing_only()
        check("补备份的文件", copied, ["config.json"])
        check("外部副本已建立",
              (store.backup_dir / "config.json").exists(), True)

        # 再调一次不应该重复（已存在就跳过）
        check("已存在时不重复补", store.backup_missing_only(), [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# -------------------------------------------------------------- 脏备份容错

def test_corrupt_backup_does_not_crash():
    print("\n=== ⑤ 备份损坏不拖垮启动 ===")
    root, plugin_dir = make_env()
    try:
        store = DataStore(plugin_dir, "com.test.duty")
        store.write_config({"ok": True})
        # 把外部备份写坏
        (store.backup_dir / "config.json").write_text("{坏掉的 json", encoding="utf-8")
        # 删掉插件目录的（模拟升级后要靠备份恢复，但备份是坏的）
        shutil.rmtree(plugin_dir / "data")

        restored = store.restore_if_missing()
        check("坏备份不会被拷进去", restored, [])
        check("读配置返回 None 而不是抛异常", store.read_config(), None)
        check("读历史返回 None 而不是抛异常", store.read_history(), None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 原子写入

def test_atomic_write_no_partial_file():
    print("\n=== ⑥ 原子写入 ===")
    root, plugin_dir = make_env()
    try:
        store = DataStore(plugin_dir, "com.test.duty")
        store.write_config({"n": 1})
        store.write_config({"n": 2})
        # 不应留下 .tmp 残留
        leftovers = list((plugin_dir / "data").glob("*.tmp")) + \
                    list(store.backup_dir.glob("*.tmp"))
        check("没有 .tmp 残留", [p.name for p in leftovers], [])
        check("内容是最后一次写入",
              json.loads((plugin_dir / "data/config.json").read_text(encoding="utf-8")),
              {"n": 2})
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ 备份目录推导

def test_backup_dir_location():
    print("\n=== ⑦ 备份目录位置 ===")
    root, plugin_dir = make_env()
    try:
        d = backup_dir_for(plugin_dir, "com.test.duty")
        # 必须在插件目录之外
        check("不在插件目录内", str(d).startswith(str(plugin_dir)), False)
        # 落在 configs/plugin-data/<id> 下
        check("落在 configs/plugin-data/<id>",
              d.relative_to(root).as_posix(),
              "configs/plugin-data/com.test.duty")
        # 插件目录被删重建后，备份目录仍然健在
        shutil.rmtree(plugin_dir)
        plugin_dir.mkdir()
        check("重建后备份目录仍在", d.exists(), True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    print("升级丢数据 → 自动恢复：回归测试")
    test_write_to_both_places()
    test_restore_after_overwrite_install()
    test_never_overwrite_existing()
    test_backup_missing_only()
    test_corrupt_backup_does_not_crash()
    test_atomic_write_no_partial_file()
    test_backup_dir_location()
    print(f"\n{'=' * 50}\npassed {passed}, failed {failed}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
