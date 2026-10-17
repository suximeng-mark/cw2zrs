# -*- coding: utf-8 -*-
"""打包产物卫生守卫。

背景：Class Widgets SDK 的 `cw-plugin-pack` 用一份**硬编码**的排除集
（DEFAULT_IGNORE_PATTERNS）来挑文件，**不读 .gitignore**，也没有任何
配置项可以扩展（cwplugin.json 里没有相关字段）。所以：

  - `.workbuddy/`（本项目的工作笔记）、`tests/`、`.github/`、`.trae/`
    这些目录名不在排除集里，会被原样打进 .cwplugin 产物
  - CI 上是干净 checkout，所以 `.workbuddy/` 与 `data/` 不存在
  - 但 `tests/` 和 `.github/` 是**提交进仓库的**，CI 打的包里一直带着它们
  - `data/` 更严重：它是运行时私有数据目录，带出厂等于让每个新用户
    都拿到别人的成员姓名与考勤历史

解法是 `tools/pack.py`（打包前暂存这些目录、打完包原样放回）。
本测试**走包装器**跑真实打包，检查 zip 条目——不是只检查 .gitignore
有没有写（.gitignore 对打包器无效）。

运行方式（需要已安装 class-widgets-sdk）：
    python tests/test_packaging_hygiene.py
"""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 打包器硬编码排除集之外的目录 —— 它们不该出现在产物里
FORBIDDEN_PREFIXES = {
    ".workbuddy": "本项目的工作笔记/临时脚本，不该随插件分发",
    ".github": "CI 配置，产物不需要",
    ".trae": "编辑器配置",
    "tests": "开发用测试，产物不需要",
    "data": "运行时私有数据（真实姓名/考勤），不应随分发包出厂",
    "tools": "打包脚本自身，打包时还在被用",
    "__pycache__": "Python 缓存（打包器已排除，这里双保险）",
}

# 必须出现在产物里 —— 少了插件就装不起来
REQUIRED = ["main.py", "cwplugin.json", "assets/settings.qml", "assets/widget.qml"]

passed = failed = 0


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n       期望 {want!r}\n       实际 {got!r}")


def pack_with_wrapper(out_dir: Path):
    """通过 tools/pack.py 打包到 out_dir。

    产物直接落在系统临时目录而不是仓库根：本机沙箱对桌面目录的
    删除操作会拦（safe-delete），测试不该去删仓库里的文件。
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "pack.py"),
         "--format", "cwplugin", "--out-dir", str(out_dir)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    produced = out_dir / "com.studentondutyshow.com.cwplugin"
    if r.returncode != 0 or not produced.exists():
        print((r.stdout or "")[-1200:])
        print((r.stderr or "")[-1200:])
        raise SystemExit("包装器打包失败")
    return produced


def main() -> int:
    try:
        from ClassWidgets.SDK import __version__ as sdk_ver
    except Exception:
        print("未安装 class-widgets-sdk，跳过（pip install class-widgets-sdk）")
        return 0
    print(f"SDK 版本 {sdk_ver}\n")

    tmp = Path(tempfile.mkdtemp(prefix="cw2zrs_hygiene_"))
    out = tmp / "probe.cwplugin"
    try:
        produced = pack_with_wrapper(tmp)

        with zipfile.ZipFile(produced) as z:
            names = z.namelist()
            bad = z.testzip()

        print("=== 产物结构 ===")
        check("zip 完整", bad, None)
        print(f"  条目数 {len(names)}，体积 {produced.stat().st_size:,} B\n")

        print("=== 必须包含 ===")
        for rq in REQUIRED:
            check(rq, rq in names, True)

        print("\n=== 不该包含 ===")
        tops = {n.split("/")[0] for n in names}
        for prefix, why in sorted(FORBIDDEN_PREFIXES.items()):
            check(f"{prefix}/ 已排除（{why}）", prefix in tops, False)

        print("\n=== 产物顶层实际内容 ===")
        for t in sorted(tops - set(FORBIDDEN_PREFIXES)):
            print(f"    {t}")
        return failed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    code = main()
    print(f"\n{'=' * 46}\npassed {passed}, failed {code}")
    sys.exit(code)