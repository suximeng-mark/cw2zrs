# -*- coding: utf-8 -*-
"""插件私有数据的双写与恢复。

## 为什么需要这个模块

插件把用户数据（分组/成员/假期/轮换设置/考勤历史）写在**插件安装目录内**
的 `data/` 下：

    <CW2>/plugins/com.studentondutyshow.com/data/config.json
    <CW2>/plugins/com.studentondutyshow.com/data/history.json

而 Class Widgets 2 的插件升级走 `configs.json` 里的 `pending_operations`，
类型是 `"type": "install"` —— **完全覆盖安装**：整个插件目录会被重建。

实测三种可能的安装方式对 `data/` 的影响：

    先删整个目录再解压   →  data/ 全丢
    直接覆盖解压          →  data/ 保留
    逐文件覆盖            →  data/ 保留

用户实际遇到的是第一种，所以**每次升级数据都会丢**。

## 解法：双写 + 自动恢复

数据仍然留在插件目录（不进核心 `configs.json`，保住那份性能优势 —— 见
`main.py` 里 `DutyConfig` 上方的注释），但**每次落盘都同步一份到插件目录
之外**：

    <CW2>/configs/plugin-data/<plugin_id>/config.json
    <CW2>/configs/plugin-data/<plugin_id>/history.json

升级覆盖后插件目录被重建、`data/` 消失，但外部副本还在。下次启动时
检测到 `data/` 缺失就自动恢复，用户无感。

## 为什么外部目录选在 <CW2>/configs/ 下

- 它**不在插件目录里**，升级不会碰它
- 它跟着 CW2 走，卸载 CW2 时一起清掉，不留垃圾
- `configs/` 本来就是 CW2 的配置目录，语义一致
- 相比 `%APPDATA%` 之类需要猜路径的地方，从插件位置往上两级即可推导，
  不依赖 SDK 是否暴露了「应用数据目录」接口

## 绝不写到别的插件目录

CW2 把**每个插件目录**都加进 `sys.path`，插件之间并不是完全隔离的。
早期版本在推导不出 CW2 根目录时，会把备份写到 `plugins/` 下的同级隐藏
目录（`plugins/.<id>-datastore/`）——那已经越过了本插件的边界，恰好是
「其它插件目录里冒出本插件配置文件」这类反馈最容易踩中的坑。

现在有两条硬约束：

1. 只有**确认**推导出的目录是 CW2 根（存在 `configs/` 或 `plugins/`）时，
   才允许写 `configs/plugin-data/<plugin_id>/`；目录名严格按插件 ID 隔离。
2. 任何异常布局 / 创建失败，一律退回到**插件目录内部**的 `.datastore/`，
   宁可失去升级兜底，也绝不在 `plugins/` 或其它位置创建文件。
3. 所有写入目标都要通过 `_writable_target()` 校验：必须位于自身的
   `data/` 或 `backup_dir/` 之内，否则直接拒绝写入。

## 写入的原子性

备份用「先写 `.tmp` 再 `os.replace`」——和插件自己的落盘策略一致。
中途断电/崩溃时，备份要么是旧的完整版本，要么是新的完整版本，
不会留下半截 JSON 把下次启动搞崩。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

# 插件目录往上两级是 CW2 根目录，再下 configs/plugin-data/<plugin_id>
BACKUP_SUBDIR = ("configs", "plugin-data")

# 参与备份的文件名（相对插件的 data/ 目录）
BACKUP_FILES = ("config.json", "history.json")


def _safe_plugin_id(plugin_id: str) -> str:
    """插件 ID 只能当**单层目录名**用，杜绝 `../` 之类把备份写到别处。"""
    pid = str(plugin_id or "").strip()
    if (not pid or pid in (".", "..") or "/" in pid or "\\" in pid
            or "\x00" in pid or pid.startswith(".")):
        raise ValueError(f"invalid plugin id: {plugin_id!r}")
    return pid


def backup_dir_for(plugin_dir: Path, plugin_id: str) -> Path:
    """外部备份目录：<CW2>/configs/plugin-data/<plugin_id>/。

    只有能确认 CW2 根目录时才写到插件目录外；布局异常则退回插件目录内的
    `.datastore/`，**绝不在 plugins/ 下或其它插件目录创建任何文件**。
    """
    pid = _safe_plugin_id(plugin_id)
    plugin_dir = Path(plugin_dir).resolve()
    parents = plugin_dir.parents
    root = parents[1] if len(parents) >= 2 else plugin_dir.parent

    # 标准布局 <CW2>/plugins/<id>：parents[0]=plugins, parents[1]=CW2。
    # 必须验证 root 真的像 CW2 根目录，避免嵌套安装时误把 plugins/ 当根。
    if (root / "configs").is_dir() or (root / "plugins").is_dir():
        candidate = root.joinpath(*BACKUP_SUBDIR) / pid
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            pass

    fallback = plugin_dir / ".datastore" / pid
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _atomic_write_json(target: Path, payload: object) -> bool:
    """原子写 JSON：先写临时文件再 replace。成功返回 True。"""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _is_valid_json(path: Path) -> bool:
    """文件能否被解析成 JSON。损坏的备份不能拿去恢复。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            json.load(f)
        return True
    except (OSError, ValueError):
        return False


class DataStore:
    """插件私有数据的双写存储。

    用法：

        store = DataStore(plugin_dir, plugin_id)
        store.restore_if_missing()      # on_load 早期调用
        store.write_config(payload)     # 落盘时调用（内部同时写两处）
        store.write_history(records)    # 同上
    """

    def __init__(self, plugin_dir: Path, plugin_id: str) -> None:
        self.plugin_dir = Path(plugin_dir).resolve()
        self.plugin_id = _safe_plugin_id(plugin_id)
        self.data_dir = self.plugin_dir / "data"
        self.backup_dir = backup_dir_for(self.plugin_dir, self.plugin_id)

    # ------------------------------------------------------------ 写入边界守卫

    def _writable_target(self, target: Path) -> bool:
        """目标必须落在自己的 data/ 或备份目录内，否则拒绝写入。

        CW2 会把所有插件目录加进 sys.path，模块/路径并不天然隔离。这道守卫
        保证即使将来有人误改了路径推导，本插件也不可能把 config.json 写到
        其它插件的目录里。
        """
        try:
            resolved = Path(target).resolve()
        except OSError:
            return False
        for base in (self.data_dir, self.backup_dir):
            try:
                resolved.relative_to(base.resolve())
                return True
            except (ValueError, OSError):
                continue
        return False

    # ------------------------------------------------------------------ 恢复

    def restore_if_missing(self) -> List[str]:
        """插件目录里缺文件时，从外部备份恢复。返回恢复的文件名列表。

        只在**插件目录确实没有**该文件时才恢复 —— 绝不覆盖已有数据。
        备份内容损坏时跳过恢复：宁可让插件用默认值启动，
        也不要往插件目录里塞一份解析不了的 JSON。
        """
        restored: List[str] = []
        for name in BACKUP_FILES:
            target = self.data_dir / name
            if target.exists() or not self._writable_target(target):
                continue
            source = self.backup_dir / name
            if not source.exists() or not self._writable_target(source):
                continue
            if not _is_valid_json(source):
                continue
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                restored.append(name)
            except OSError:
                continue
        return restored

    def backup_missing_only(self) -> List[str]:
        """把插件目录里已有、但外部还没有的文件补一份到外部。

        用于**首次升级到本版本**的场景：用户原有数据在插件目录里，
        但外部备份是空的。此时先补备份，之后的升级才有兜底。
        """
        copied: List[str] = []
        for name in BACKUP_FILES:
            source = self.data_dir / name
            target = self.backup_dir / name
            if not source.exists() or target.exists():
                continue
            if not (self._writable_target(source) and self._writable_target(target)):
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                copied.append(name)
            except OSError:
                continue
        return copied

    # ------------------------------------------------------------------ 写入

    def write_config(self, payload: Dict) -> bool:
        """写配置到插件目录 + 外部备份。插件目录写成功才算成功。"""
        local = self.data_dir / "config.json"
        remote = self.backup_dir / "config.json"
        if not (self._writable_target(local) and self._writable_target(remote)):
            return False
        ok = _atomic_write_json(local, payload)
        if ok:
            _atomic_write_json(remote, payload)
        return ok

    def write_history(self, records: List[Dict]) -> bool:
        """写历史到插件目录 + 外部备份。"""
        payload = {"records": records}
        local = self.data_dir / "history.json"
        remote = self.backup_dir / "history.json"
        if not (self._writable_target(local) and self._writable_target(remote)):
            return False
        ok = _atomic_write_json(local, payload)
        if ok:
            _atomic_write_json(remote, payload)
        return ok

    # ------------------------------------------------------------------ 读取

    def read_config(self) -> Optional[Dict]:
        """读配置：插件目录优先，没有则读外部备份。"""
        for path in (self.data_dir / "config.json", self.backup_dir / "config.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (FileNotFoundError, OSError, ValueError):
                continue
            if isinstance(payload, dict):
                return payload
        return None

    def read_history(self) -> Optional[List[Dict]]:
        """读历史：插件目录优先，没有则读外部备份。"""
        for path in (self.data_dir / "history.json", self.backup_dir / "history.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (FileNotFoundError, OSError, ValueError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get("records"), list):
                return payload["records"]
            if isinstance(payload, list):
                return payload
        return None

    # ------------------------------------------------------------------ 诊断

    def status(self) -> Dict[str, object]:
        """当前存储状态，供界面展示与排障。"""
        return {
            "data_dir": str(self.data_dir),
            "backup_dir": str(self.backup_dir),
            "config_in_data": (self.data_dir / "config.json").exists(),
            "config_in_backup": (self.backup_dir / "config.json").exists(),
            "history_in_data": (self.data_dir / "history.json").exists(),
            "history_in_backup": (self.backup_dir / "history.json").exists(),
        }
