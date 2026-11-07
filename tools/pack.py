# -*- coding: utf-8 -*-
"""插件打包包装器：在**仓库副本**里打包，绝不动工作区。

## 为什么需要它

Class Widgets SDK 的 `cw-plugin-pack` 用一份**硬编码**的排除集挑文件
（`PluginPackager.DEFAULT_IGNORE_PATTERNS`），它**不读 .gitignore**，
`cwplugin.json` 里也没有任何字段可以扩展排除项。可用的排除名只有：

    __pycache__  *.pyc  *.pyo  *.pyd
    .DS_Store  Thumbs.db  desktop.ini
    .git  .gitignore  .gitattributes
    .venv  venv  env  .idea  .vscode
    *.cwplugin  *.zip
    dist  build  *.egg-info
    cwplugin.local.json

于是本仓库里这些内容会被原样打进 .cwplugin：

    .workbuddy/            工作笔记与内部细节，不该对外分发
    .github/               CI 配置
    .trae/                 编辑器配置
    tests/                 开发用测试，产物用不上
    tools/                 打包脚本自身，打包时还在被用
    data/                  运行时私有数据；带出厂用户装上就带着别人的考勤历史
    RinUI/config/          ⚠ RinUI（CW2 主程序 UI 框架）的**全局主题配置**
    fix_cw_config.py       ⚠ 会 rglob 全盘找 configs.json 并重写跨插件字段
    pyproject.toml         Python 工程元数据，运行时不读
    .git-cliff.toml        changelog 工具配置

⚠ 的两项是「其它插件目录里冒出本插件配置文件」类反馈的直接来源：
CW2 会把**每个插件目录**加进 `sys.path`，安装时又把包内文件原样解压到
`plugins/<id>/`。插件包里夹带全局配置文件/开发脚本，等于把它们塞进了
所有插件共享的搜索路径。因此产物采用**顶层白名单**自检，宁可打包失败
也不让这些文件出厂。

## 为什么是「复制到临时区打包」

第一版是「把目录移走、打完包移回」，实测**把 `.workbuddy/` 弄丢过**——
暂存/还原本身是破坏性的：只要中途任何一步出问题（跨盘 move、异常退出、
进程被杀），源目录就没了。工作笔记和测试都在里面，丢了要重写。

现在改成：把源码**复制**一份到系统临时目录，在副本里删掉这些目录，
然后对副本打包。工作区从头到尾只被读，不删不改任何文件——
即使打包失败或进程被杀，最多是临时目录里留下垃圾。

用法：
    python tools/pack.py                      # 两种格式都打到仓库根
    python tools/pack.py --format cwplugin
    python tools/pack.py --out-dir build      # 打到别处

CI 也用它（见 .github/workflows/release.yml），保证线上包与本地一致。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

# 允许 --packager 覆盖；CI 里 `pip install -e .` 后可直接从 PATH 找到
PACKAGER: str | None = None


def find_packager() -> str | None:
    """定位 cw-plugin-pack CLI。

    CI 里它在 PATH；本地常装在**另一个** Python 版本下（例如项目用 3.12、
    终端默认 3.13），只查 sys.executable 同级的 Scripts/ 会找不到。
    """
    names = ("cw-plugin-pack.exe", "cw-plugin-pack")
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit
    candidates: list[Path] = []
    for base in (Path(sys.executable).parent / "Scripts",
                 Path(sys.executable).parent / "bin"):
        candidates.extend(base / name for name in names)
    if sys.platform == "win32":
        for name in names:
            candidates.extend(sorted(
                Path.home().glob(
                    f"AppData/Local/Programs/Python/*/Scripts/{name}"),
                reverse=True,
            ))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None

# 副本里要删掉的目录（打包器不排除它们，但产物不需要）
EXCLUDED_DIRS = [
    ".workbuddy", ".github", ".trae", "tests", "data", "tools",
    "RinUI",            # RinUI 全局主题配置，绝不能随插件分发
    "__pycache__",
]

# 副本里要删掉的文件（顶层开发/工程文件）
EXCLUDED_FILES = [
    "fix_cw_config.py",  # 会重写全局 configs.json 的跨插件字段
    # ⚠ pyproject.toml 必须留在 stage：cw-plugin-pack 靠它的 dependencies
    #   决定要注入哪些依赖到 libs/。删了会打出缺依赖的残包。
    #   打包完成后由 sanitize_archive() 从产物里剔除。
    ".git-cliff.toml",
    "cwplugin.local.json",
]

# 打包器会把它读到的工程文件一并写进产物，打包后统一剔除
DROP_FROM_ARCHIVE = {"pyproject.toml", ".git-cliff.toml", "fix_cw_config.py"}

# 产物**顶层**白名单：多一个都不行
ALLOWED_TOP = {
    "main.py",
    "_cw2zrs_datastore.py",
    "cwplugin.json",
    "icon.png",
    "README.md",
    "LICENSE",
    "assets",
    "libs",
}

# 任意层级都禁止出现的文件/目录名（含明确诊断信息）
FORBIDDEN_NAMES = {
    "fix_cw_config.py", "pyproject.toml", ".git-cliff.toml",
    "config.json", "history.json", "configs.json", "rin_ui.json",
}

# 必须出现在产物里
REQUIRED = [
    "main.py", "_cw2zrs_datastore.py", "cwplugin.json",
    "assets/settings.qml", "assets/widget.qml", "icon.png",
]

# 复制源码时顺带跳过的（省时间：.git 有 17 MB）
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", "*.cwplugin", "*.zip", "*.egg-info", ".venv",
)


def stage_source(stage: Path) -> list[str]:
    """把源码复制到 stage 并删掉不该进包的内容。返回实际删掉的项名。"""
    # copytree 要求目标不存在：先删掉 mkdtemp 建出来的空壳
    stage.rmdir()
    shutil.copytree(ROOT, stage, ignore=COPY_IGNORE, symlinks=True)
    dropped = []
    for name in EXCLUDED_DIRS:
        target = stage / name
        if target.is_dir():
            shutil.rmtree(target)
            dropped.append(name + "/")
    for name in EXCLUDED_FILES:
        target = stage / name
        if target.is_file():
            target.unlink()
            dropped.append(name)
    return dropped


def sanitize_archive(path: Path) -> list[str]:
    """剔除打包器夹带进产物的工程/配置文件，返回被删条目。

    必须先打包再净化：pyproject.toml 在 stage 里要留给打包器读依赖，
    但最终产物不该带它（以及任何本插件的配置文件）。
    """
    with zipfile.ZipFile(path, "r") as z:
        items = [(info, z.read(info.filename)) for info in z.infolist()]

    removed = [
        info.filename for info, _ in items
        if PurePosixPath(info.filename).name in DROP_FROM_ARCHIVE
        or info.filename.startswith("RinUI/")
        or (info.filename.lower().endswith(".json")
            and info.filename != "cwplugin.json"
            and not info.filename.startswith("libs/"))
    ]
    if not removed:
        return []

    tmp = path.with_name(path.name + ".clean")
    removed_set = set(removed)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for info, data in items:
            if info.filename not in removed_set:
                out.writestr(info, data)
    os.replace(tmp, path)
    return removed


def validate_entries(entries: list[str]) -> list[str]:
    """产物自检：返回问题描述列表，空列表表示通过。"""
    problems: list[str] = []
    tops = {n.split("/")[0] for n in entries}

    extra = sorted(tops - ALLOWED_TOP)
    if extra:
        problems.append(f"顶层出现白名单外条目：{extra}")

    # 除 cwplugin.json 外，插件自身不应带任何 .json（libs/ 内第三方资源除外）
    stray_json = sorted(
        n for n in entries
        if n.lower().endswith(".json")
        and n != "cwplugin.json"
        and not n.startswith("libs/")
    )
    if stray_json:
        problems.append(f"混入配置文件（非 cwplugin.json）：{stray_json[:10]}")

    banned = sorted(
        n for n in entries
        if PurePosixPath(n).name in FORBIDDEN_NAMES
        or n.startswith("RinUI/")
        or n.lower().endswith(".toml") and not n.startswith("libs/")
    )
    if banned:
        problems.append(f"混入禁止文件：{banned[:10]}")

    absent = [r for r in REQUIRED if r not in entries]
    if absent:
        problems.append(f"缺少必需文件：{absent}")

    # 路径穿越：CW2 安装器会拒绝，这里提前拦下
    unsafe = [n for n in entries if ".." in PurePosixPath(n).parts]
    if unsafe:
        problems.append(f"路径不安全的条目：{unsafe[:10]}")
    return problems


def pack(fmt: str, out_dir: Path) -> Path | None:
    """在临时副本上打包，产物落到 out_dir。失败返回 None。"""
    packager = PACKAGER or find_packager()
    if packager is None:
        print("  ❌ 未找到 cw-plugin-pack。请先 `pip install -e .`，"
              "或用 --packager 指定可执行文件路径。")
        return None
    cmd = [packager]

    stage = Path(tempfile.mkdtemp(prefix="cw2zrs_stage_"))
    try:
        dropped = stage_source(stage)
        print(f"  副本已排除：{', '.join(dropped) or '（无）'}")

        target = stage / f"com.studentondutyshow.com.{fmt}"
        print(f"\n=== 打包 {fmt} ===")
        r = subprocess.run(cmd + ["--format", fmt, "-o", str(target)],
                           cwd=str(stage), capture_output=True, text=True)
        tail = (r.stdout or "") + (r.stderr or "")
        for line in tail.strip().splitlines()[-5:]:
            print("   ", line)

        if r.returncode != 0 or not target.exists():
            print(f"  ❌ 打包失败（退出码 {r.returncode}）")
            return None

        cleaned = sanitize_archive(target)
        if cleaned:
            print(f"  已从产物剔除 {len(cleaned)} 项：{cleaned[:6]}")

        with zipfile.ZipFile(target) as z:
            entries = z.namelist()
        tops = {n.split("/")[0] for n in entries}

        problems = validate_entries(entries)
        if problems:
            for p in problems:
                print(f"  ❌ {p}")
            return None

        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / target.name
        # copy 而非 move：桌面目录的删除/重命名会被安全钩子拦
        shutil.copyfile(target, dest)
        print(f"  ✅ {dest.name}  {dest.stat().st_size:,} B"
              f"（顶层 {len(tops)} 项，已自检）")
        return dest
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--format", choices=["cwplugin", "zip", "both"], default="both")
    ap.add_argument("--out-dir", help="产物输出目录，默认为仓库根")
    ap.add_argument("--packager", help="cw-plugin-pack 可执行文件路径（默认自动探测）")
    args = ap.parse_args()

    global PACKAGER
    PACKAGER = args.packager

    formats = ["cwplugin", "zip"] if args.format == "both" else [args.format]
    out_dir = Path(args.out_dir).resolve() if args.out_dir else ROOT

    print("Class Widgets 插件打包（副本打包，不动工作区）")
    results = [(f, pack(f, out_dir)) for f in formats]

    bad = [f for f, p in results if p is None]
    if bad:
        print(f"\n失败格式：{bad}")
        return 1
    print("\n全部完成：")
    for _, p in results:
        print(f"    {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())