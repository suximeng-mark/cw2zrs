# -*- coding: utf-8 -*-
"""
CW2 configs.json 自动修复脚本
用途：解决 CW2 的「启用插件」按钮不持久化 configs.json 的问题，
      确保值日生插件被正确启用并显示在桌面。

执行的三项修复（均为幂等操作，可重复运行）：
  1. 将 "com.classwidgets.duty-student" 加入 plugins.enabled
  2. 将 interactions.hide.state 置为 false（避免部件被默认隐藏）
  3. 在 widgets_presets.default 中加入值日生部件实例

用法:
    python fix_cw_config.py            # 自动探测 CW2 目录
    python fix_cw_config.py --path "C:\\path\\to\\CW2"  # 指定 CW2 根目录
    python fix_cw_config.py --dry-run  # 仅预览，不写入
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PLUGIN_ID = "com.classwidgets.duty-student"
WIDGET_TYPE_ID = "com.classwidgets.duty-student.widget"
WIDGET_INSTANCE_ID = "d9f3a2b1-4c5e-6f7a-8b9c-0d1e2f3a4b5c"

# 常见 CW2 安装目录候选（按优先级）
CANDIDATE_ROOTS = [
    r"C:\Users\Lenovo\Desktop\吸大鼻溜2\吸大鼻溜2",
    r"C:\Users\Lenovo\Desktop\吸大鼻溜2",
    os.path.expanduser("~\\Desktop\\ClassWidgets"),
    os.path.expanduser("~\\Desktop\\ClassWidgets 2"),
    os.getcwd(),
]


def find_config_path(explicit: str | None = None) -> Path | None:
    """定位 configs.json，优先使用显式指定的根目录。"""
    roots = [Path(explicit)] if explicit else [Path(p) for p in CANDIDATE_ROOTS]
    for root in roots:
        if not root:
            continue
        cfg = root / "configs" / "configs.json"
        if cfg.is_file():
            return cfg
    # 兜底：在用户家目录下搜索
    for base in (Path.home() / "Desktop", Path.home()):
        for hit in base.rglob("configs.json"):
            if "configs" in str(hit.parent):
                return hit
    return None


def backup_config(path: Path) -> Path | None:
    """写之前备份原文件，命名带时间戳。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(f"configs.json.bak_{ts}")
    try:
        shutil.copy2(path, bak)
        return bak
    except OSError:
        return None


def fix_plugins_enabled(cfg: dict) -> bool:
    """修复 1：把插件 ID 加入 plugins.enabled。"""
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    if PLUGIN_ID in enabled:
        return False
    enabled.append(PLUGIN_ID)
    return True


def fix_hide_state(cfg: dict) -> bool:
    """修复 2：把 interactions.hide.state 置 false。"""
    interactions = cfg.setdefault("interactions", {})
    hide = interactions.setdefault("hide", {})
    if hide.get("state") is False:
        return False
    hide["state"] = False
    return True


def fix_widget_preset(cfg: dict) -> bool:
    """修复 3：在 widgets_presets.default 中添加值日生部件实例。"""
    prefs = cfg.setdefault("preferences", {})
    presets = prefs.setdefault("widgets_presets", {})
    default = presets.setdefault("default", [])

    for item in default:
        if isinstance(item, dict) and item.get("type_id") == WIDGET_TYPE_ID:
            return False  # 已存在

    default.append({
        "type_id": WIDGET_TYPE_ID,
        "instance_id": WIDGET_INSTANCE_ID,
        "settings": {},
    })
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="CW2 configs.json 自动修复")
    parser.add_argument("--path", help="CW2 根目录（包含 configs/ 子目录）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    args = parser.parse_args()

    cfg_path = find_config_path(args.path)
    if not cfg_path:
        print("[ERROR] 未找到 configs.json。请用 --path 指定 CW2 根目录。")
        return 2

    print(f"[INFO] 目标配置文件: {cfg_path}")

    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR] 读取 configs.json 失败: {e}")
        return 3

    changes: list[str] = []

    if fix_plugins_enabled(cfg):
        changes.append(f"已将 '{PLUGIN_ID}' 加入 plugins.enabled")
    else:
        changes.append(f"plugins.enabled 已包含 '{PLUGIN_ID}'（跳过）")

    if fix_hide_state(cfg):
        changes.append("interactions.hide.state 已置为 false")
    else:
        changes.append("interactions.hide.state 已为 false（跳过）")

    if fix_widget_preset(cfg):
        changes.append(f"已在 widgets_presets.default 添加 '{WIDGET_TYPE_ID}' 实例")
    else:
        changes.append(f"widgets_presets.default 已含 '{WIDGET_TYPE_ID}'（跳过）")

    print("\n修复结果：")
    for line in changes:
        print(f"  - {line}")

    if args.dry_run:
        print("\n[DRY-RUN] 未写入文件。去掉 --dry-run 以实际应用。")
        return 0

    bak = backup_config(cfg_path)
    if bak:
        print(f"\n[BACKUP] 已备份原文件到: {bak}")
    else:
        print("\n[WARN] 备份失败，继续写入。")

    try:
        with cfg_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except OSError as e:
        print(f"[ERROR] 写入 configs.json 失败: {e}")
        return 4

    print(f"\n[OK] 配置已写入: {cfg_path}")
    print("下一步：重启 Class Widgets 2 使配置生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
