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

于是本仓库里这些目录会被原样打进 .cwplugin：

    .workbuddy/   工作笔记与内部细节，不该对外分发
    .github/      CI 配置
    .trae/        编辑器配置
    tests/        196 KB 开发用测试，产物用不上
    tools/        打包脚本自身，打包时还在被用
    data/         运行时私有数据目录；带出厂的话用户装上就带着别人的考勤历史

`.workbuddy/` 与 `data/` 虽然在 .gitignore 里（所以 CI 的干净 checkout
里不存在），但 `tests/` 和 `.github/` 是**提交进仓库的**，CI 打的包里
一直带着它们。

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
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 副本里要删掉的目录（打包器不排除它们，但产物不需要）
EXCLUDED = [".workbuddy", ".github", ".trae", "tests", "data", "tools"]

# 产物里不该出现的顶层项，用于自检
FORBIDDEN = set(EXCLUDED) | {"__pycache__"}

# 必须出现在产物里
REQUIRED = ["main.py", "cwplugin.json", "assets/settings.qml", "assets/widget.qml"]

# 复制源码时顺带跳过的（省时间：.git 有 17 MB）
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", "*.cwplugin", "*.zip", "*.egg-info", ".venv",
)


def stage_source(stage: Path) -> list[str]:
    """把源码复制到 stage 并删掉不该进包的目录。返回实际删掉的目录名。"""
    # copytree 要求目标不存在：先删掉 mkdtemp 建出来的空壳
    stage.rmdir()
    shutil.copytree(ROOT, stage, ignore=COPY_IGNORE, symlinks=True)
    dropped = []
    for name in EXCLUDED:
        target = stage / name
        if target.exists():
            shutil.rmtree(target)
            dropped.append(name)
    return dropped


def pack(fmt: str, out_dir: Path) -> Path | None:
    """在临时副本上打包，产物落到 out_dir。失败返回 None。"""
    exe = Path(sys.executable).parent / "Scripts" / "cw-plugin-pack.exe"
    cmd = [str(exe)] if exe.exists() else ["cw-plugin-pack"]

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

        with zipfile.ZipFile(target) as z:
            entries = z.namelist()
        tops = {n.split("/")[0] for n in entries}

        leaked = sorted(tops & FORBIDDEN)
        if leaked:
            print(f"  ❌ 产物里混入了不该有的目录：{leaked}")
            return None
        absent = [r for r in REQUIRED if r not in entries]
        if absent:
            print(f"  ❌ 产物缺少必需文件：{absent}")
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
    args = ap.parse_args()

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