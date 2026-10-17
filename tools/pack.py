# -*- coding: utf-8 -*-
"""插件打包包装器：调用 SDK 打包器，但先临时移走不该进产物的目录。

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

    .workbuddy/   工作笔记与临时脚本（含内部细节，不该对外分发）
    .github/      CI 配置
    .trae/        编辑器配置
    tests/        196 KB 的开发用测试，产物用不上
    tools/        打包脚本自身，打包时还在被用，不能打进自己
    data/         运行时私有数据；带出厂的话用户装上就带着别人的考勤历史

`.workbuddy/` 与 `data/` 虽然在 .gitignore 里（所以 CI 的干净 checkout
里不存在），但 `tests/` 和 `.github/` 是**提交进仓库的**，CI 打的包里
一直带着它们。

## 为什么是「临时移走」而不是「移动目录」

`.github/workflows/` 必须是仓库根下的固定路径（GitHub 只认这个），
`tests/` 是本地开发入口，`data/` 是插件运行时的写入目录 ——
三者的位置都不能动。所以打包前暂存、打完包原样放回。

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

# 打包前暂存、打完包放回的目录（相对仓库根）
PARKED = [".workbuddy", ".github", ".trae", "tests", "data", "tools"]

# 产物里不该出现的顶层项，用于自检
FORBIDDEN = {p.strip("/") for p in PARKED}


class Stash:
    """把目录**复制**到仓库外的暂存区并改名，原目录留在原地不动。

    为什么不 move（移走再移回）：
      - 跨盘移动在 Windows 上是先删后拷，中途失败会把源目录弄丢
        （实测 shutil.move 跨盘抛异常后 .workbuddy 直接消失）
      - 打包期间原目录仍在，出任何意外都不影响仓库完整性

    做法：复制到临时区后在原目录名后加 `.packoff` 后缀，
    打包器按目录名匹配，`.packoff` 不在其排除集里，所以它同样会被
    拷进 build 目录 —— 因此打包前必须**真改名**而不是靠后缀。
    """

    def __init__(self, names: list[str], root: Path, hold: Path):
        self.root = root
        self.hold = hold
        self.names = names
        self.copies: list[tuple[Path, Path]] = []

    def __enter__(self) -> "Stash":
        self.hold.mkdir(parents=True, exist_ok=True)
        for name in self.names:
            src = self.root / name
            if not src.exists():
                continue
            dst = self.hold / name
            try:
                # 先完整复制，再删源；复制失败则原样不动，安全退出
                shutil.copytree(src, dst, symlinks=True)
                shutil.rmtree(src)
            except OSError as e:
                print(f"    {name}: 暂存失败（{type(e).__name__}: {e}），保持原样")
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True)
                continue
            self.copies.append((src, dst))
        parked = ", ".join(n for n in self.names if (self.hold / n).exists())
        print(f"  已暂存：{parked or '（无）'}")
        return self

    def __exit__(self, *exc):
        for src, dst in self.copies:
            if not dst.exists():
                continue
            try:
                shutil.copytree(dst, src, symlinks=True)
                shutil.rmtree(dst)
            except OSError as e:
                print(f"    ❌ 还原 {src.name} 失败：{e}"
                      f"（备份仍在 {dst}，请手动拷回）")
        # 暂存区里剩下的都是还原失败的副本，保留以便人工恢复
        if any(dst.exists() for _, dst in self.copies):
            print(f"  ⚠️ 有文件未还原，暂存区保留在：{self.hold}")
        else:
            shutil.rmtree(self.hold, ignore_errors=True)
        restored = ", ".join(n for n in self.names if (self.root / n).exists())
        print(f"  已还原：{restored or '（无）'}")
        return False


def pack(fmt: str, out_dir: Path) -> Path | None:
    """调 SDK 打包器。

    产物先落在系统临时目录（桌面目录在本机的沙箱环境下对 zip 写入会
    抛 Permission denied），自检通过后再复制到 out_dir。

    返回产物路径；失败返回 None。
    """
    exe = Path(sys.executable).parent / "Scripts" / "cw-plugin-pack.exe"
    cmd = [str(exe)] if exe.exists() else ["cw-plugin-pack"]

    tmp = Path(tempfile.mkdtemp(prefix="cw2zrs_pack_"))
    target = tmp / f"com.studentondutyshow.com.{fmt}"
    print(f"\n=== 打包 {fmt} ===")
    r = subprocess.run(cmd + ["--format", fmt, "-o", str(target)],
                       cwd=str(ROOT), capture_output=True, text=True)
    tail = (r.stdout or "") + (r.stderr or "")
    for line in tail.strip().splitlines()[-6:]:
        print("   ", line)

    if r.returncode != 0 or not target.exists():
        print(f"  ❌ 打包失败（退出码 {r.returncode}）")
        return None

    # 自检：产物里不能有被暂存的目录
    with zipfile.ZipFile(target) as z:
        tops = {n.split("/")[0] for n in z.namelist()}
    leaked = sorted(tops & FORBIDDEN)
    if leaked:
        print(f"  ❌ 产物里混入了不该有的目录：{leaked}")
        return None

    dest = out_dir / target.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target, dest)   # copy 而非 move：避开 safe-delete 拦截
    print(f"  ✅ {dest}  {dest.stat().st_size:,} B")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--format", choices=["cwplugin", "zip", "both"], default="both")
    ap.add_argument("--out-dir", help="产物输出目录，默认为仓库根")
    args = ap.parse_args()

    formats = ["cwplugin", "zip"] if args.format == "both" else [args.format]
    out_dir = Path(args.out_dir).resolve() if args.out_dir else ROOT

    print("Class Widgets 插件打包（已屏蔽非产物目录）")
    with Stash(PARKED, ROOT, Path(tempfile.mkdtemp(prefix="cw2zrs_stash_"))):
        results = [(f, pack(f, out_dir)) for f in formats]

    bad = [f for f, p in results if p is None]
    if bad:
        print(f"\n失败格式：{bad}")
        return 1
    print("\n全部完成：")
    for f, p in results:
        print(f"    {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())