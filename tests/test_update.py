# -*- coding: utf-8 -*-
"""备用更新服务回归测试：版本比较、更新源解析、配置校验、失败路径。

网络请求全部打桩，不发真实请求；只有「实连一次」的验证放在开发机上手动跑。

运行方式（无需 CW2 环境）：
    python tests/test_update.py
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

_spec = importlib.util.spec_from_file_location(
    "_rot", ROOT / "tests" / "test_rotation.py"
)
_rot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rot)

# 测试桩里的 QTimer 没有 singleShot，补上以便走通「请求结束后通知 UI」这一步
from PySide6.QtCore import QTimer  # noqa: E402

if not hasattr(QTimer, "singleShot"):
    QTimer.singleShot = staticmethod(lambda *a, **k: None)

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


def make_plugin(settings=None):
    p = object.__new__(Plugin)
    p._settings = dict(m.DEFAULT_SETTINGS)
    if settings:
        p._settings.update(settings)
    p._update_state = {
        "status": "idle", "latest": "", "current": Plugin.current_version(p),
        "download": "", "page": "", "msg": "",
    }
    p.updateReady = types.SimpleNamespace(emit=lambda: None)
    p._update_cancelled = __import__("threading").Event()
    p._schedule_config_flush = lambda: None   # 测试里不写盘
    return p


# ------------------------------------------------------------ 版本比较
def test_version_key():
    check("纯数字", Plugin._version_key("1.9.10"), ((1, 9, 10), 1))
    check("带 v 前缀", Plugin._version_key("v2.0.0"), ((2, 0, 0), 1))
    check("预发布版", Plugin._version_key("1.0.0-beta.2"), ((1, 0, 0), 0))
    check("非数字开头", Plugin._version_key("abc"), ((0,), 1))
    check("空串", Plugin._version_key(""), ((0,), 1))


def test_is_newer():
    cases = [
        ("1.9.10", "1.9.9", True),    # 字符串比较会在这里判错
        ("1.9.9", "1.9.10", False),
        ("1.10.0", "1.9.10", True),
        ("2.0", "1.99.99", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.0-beta", "1.0.0", False),
        ("1.0.1", "1.0.0-beta", True),
        ("1.0", "1.0.0", False),      # 位数不同但数值相同
        ("", "1.0.0", False),
        ("abc", "1.0.0", False),
    ]
    for latest, current, want in cases:
        check(f"newer({latest!r}, {current!r})", Plugin._is_newer(latest, current), want)


# ------------------------------------------------------------ 更新源解析
def test_extract_update():
    gh = {
        "tag_name": "v1.12.0",
        "html_url": "https://github.com/x/y/releases/tag/v1.12.0",
        "assets": [
            {"browser_download_url": "https://a/1.zip"},
            {"browser_download_url": "https://a/p.cwplugin"},
        ],
    }
    check("GitHub 响应", Plugin._extract_update(gh),
          ("1.12.0", "https://a/p.cwplugin", "https://github.com/x/y/releases/tag/v1.12.0"))

    check("通用 JSON", Plugin._extract_update(
        {"version": "2.0.0", "download": "https://d/p.cwplugin", "page": "https://d"}),
        ("2.0.0", "https://d/p.cwplugin", "https://d"))

    check("只有页面无下载", Plugin._extract_update(
        {"version": "2.0.0", "page": "https://d"}),
        ("2.0.0", "", "https://d"))

    check("无 assets 时取首个", Plugin._extract_update(
        {"tag_name": "v1", "assets": [{"browser_download_url": "https://a/only.zip"}]}),
        ("1", "https://a/only.zip", "https://a/only.zip"))

    check("非字典响应", Plugin._extract_update("not a dict"), ("", "", ""))
    check("空字典", Plugin._extract_update({}), ("", "", ""))
    check("垃圾 assets", Plugin._extract_update({"version": "1", "assets": ["x", None]}),
          ("1", "", ""))


# ------------------------------------------------------------ 配置
def test_settings_validation():
    base = dict(m.DEFAULT_SETTINGS)
    check("默认不自动检查", base["update_auto"], False)
    check("默认用内置源", base["update_source"], "")

    ok = Plugin._normalize_settings({"update_source": "https://mirror.example/x.json"})
    check("接受 https", ok["update_source"], "https://mirror.example/x.json")
    ok = Plugin._normalize_settings({"update_source": "  http://a.b/c.json  "})
    check("接受 http 并去空格", ok["update_source"], "http://a.b/c.json")
    ok = Plugin._normalize_settings({"update_source": "file:///C:/x.json"})
    check("拒绝 file 协议", ok["update_source"], "")
    ok = Plugin._normalize_settings({"update_source": "C:/local/path"})
    check("拒绝本地路径", ok["update_source"], "")
    ok = Plugin._normalize_settings({"update_source": 123})
    check("非字符串退回空", ok["update_source"], "")
    ok = Plugin._normalize_settings({"update_auto": "yes"})
    check("非布尔退回默认", ok["update_auto"], False)
    ok = Plugin._normalize_settings({"update_auto": True})
    check("接受布尔", ok["update_auto"], True)


def test_parse_source_list():
    f = Plugin._parse_source_list
    check("单个", f("https://a/1.json"), ["https://a/1.json"])
    check("换行分隔", f("https://a/1\nhttps://b/2"), ["https://a/1", "https://b/2"])
    check("逗号分隔", f("https://a/1, https://b/2"), ["https://a/1", "https://b/2"])
    check("顿号分隔", f("https://a/1、https://b/2"), ["https://a/1", "https://b/2"])
    check("去重", f("https://a/1\nhttps://a/1"), ["https://a/1"])
    check("丢非法项", f("javascript:x\nhttps://ok/1\nfile:///c"),
          ["https://ok/1"])
    check("全非法", f("javascript:x"), [])
    check("空", f(""), [])
    check("None", f(None), [])


def test_source_selection():
    gh = m.BUILTIN_UPDATE_SOURCES[0]
    p = make_plugin()
    check("默认只用内置源", p._candidate_sources(), [gh])
    p2 = make_plugin({"update_source": "https://mirror/x"})
    check("自定义源排在最前", p2._candidate_sources(),
          ["https://mirror/x", gh])
    p3 = make_plugin({"update_source": "https://gitee/x\nhttps://b/2"})
    check("多个自定义源保持顺序", p3._candidate_sources()[:2],
          ["https://gitee/x", "https://b/2"])
    p4 = make_plugin({"update_source": gh})
    check("与内置重复时去重", p4._candidate_sources(), [gh])
    check("展示用的主源是第一个", p4._update_source_url(), gh)


def test_settings_accept_multiple():
    ok = Plugin._normalize_settings(
        {"update_source": "javascript:x, https://a/1\nhttps://b/2"})
    check("逐项校验后保留有效项", ok["update_source"].split("\n"),
          ["https://a/1", "https://b/2"])


def test_state_payload():
    p = make_plugin({"update_source": "https://mirror/x", "update_auto": True})
    st = Plugin.get_update_state(p)
    for key in ("status", "latest", "current", "download", "page", "msg",
                "source", "auto", "builtin"):
        check(f"状态含 {key}", key in st, True)
    check("auto 回显", st["auto"], True)
    check("builtin 为假", st["builtin"], False)
    p3 = make_plugin()
    check("内置时 builtin 为真", Plugin.get_update_state(p3)["builtin"], True)
    check("版本来自 cwplugin.json", Plugin.current_version(p), m._PLUGIN_VERSION)


def test_save_update_settings():
    p = make_plugin()
    check("保存成功", Plugin.save_update_settings(p, True, "https://m/x"), True)
    check("自动检查已开", p._settings["update_auto"], True)
    check("备用地址已存", p._settings["update_source"], "https://m/x")
    # _normalize_settings 的契约是「非法值保留原值」（与其余设置项一致），
    # 所以危险协议不会写进去，但也不会把已填的地址清掉
    Plugin.save_update_settings(p, True, "javascript:alert(1)")
    check("危险协议不生效（保留原值）", p._settings["update_source"], "https://m/x")
    Plugin.save_update_settings(p, True, "")
    check("主动清空可以存空", p._settings["update_source"], "")


# ------------------------------------------------------------ 失败路径
def _patch_urlopen(exc):
    import urllib.request
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(exc)


def _restore_urlopen():
    import urllib.request
    urllib.request.urlopen = _REAL_URLOPEN


_REAL_URLOPEN = None


def test_fetch_failures():
    global _REAL_URLOPEN
    import urllib.request
    _REAL_URLOPEN = urllib.request.urlopen
    import urllib.error

    # HTTP 错误
    _patch_urlopen(urllib.error.HTTPError("u", 402, "Payment Required", {}, None))
    p = make_plugin()
    p._fetch_update()
    check("HTTP 错误状态", p._update_state["status"], "error")
    check("HTTP 错误提示含全部源", "HTTP 402" in p._update_state["msg"], True)
    check("提示列出所有候选源",
          all(u in p._update_state["msg"] for u in p._candidate_sources()), True)

    # 连不上
    _patch_urlopen(urllib.error.URLError("boom"))
    p._fetch_update()
    check("连不上状态", p._update_state["status"], "error")
    check("连不上提示含原因", "boom" in p._update_state["msg"], True)

    # 响应不是合法 JSON
    import io

    class _Resp:
        def read(self, n=-1):
            return b"<html>not json</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    urllib.request.urlopen = lambda *a, **k: _Resp()
    p._fetch_update()
    check("非 JSON 状态", p._update_state["status"], "error")
    check("非 JSON 提示", "无法解析" in p._update_state["msg"], True)

    # 空壳响应：没有版本号
    class _Empty:
        def read(self, n=-1):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    urllib.request.urlopen = lambda *a, **k: _Empty()
    p._fetch_update()
    check("空壳状态", p._update_state["status"], "error")
    check("空壳提示含原因", "可识别的版本号" in p._update_state["msg"], True)

    _restore_urlopen()


def test_fetch_success_states():
    global _REAL_URLOPEN
    import urllib.request
    if _REAL_URLOPEN is None:
        _REAL_URLOPEN = urllib.request.urlopen
    cur = Plugin.current_version(make_plugin())
    major, minor, patch = (int(x) for x in cur.split(".")[:3])
    newer = f"{major}.{minor}.{patch + 1}"
    older = f"{major}.{minor}.{patch - 1}" if patch > 0 else f"{major}.{minor - 1}.9"

    def respond(payload):
        class _R:
            def read(self, n=-1):
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        urllib.request.urlopen = lambda *a, **k: _R()

    p = make_plugin()
    respond({"tag_name": f"v{newer}",
             "html_url": "https://g/page",
             "assets": [{"browser_download_url": "https://g/p.cwplugin"}]})
    p._fetch_update()
    check("发现新版本", p._update_state["status"], "available")
    check("最新版本号", p._update_state["latest"], newer)
    check("下载直链", p._update_state["download"], "https://g/p.cwplugin")
    check("当前版本已填", p._update_state["current"], cur)
    # 该用例没有配置自定义源，第一个候选就是内置 GitHub
    check("记录了命中源", p._update_state["source"], m.BUILTIN_UPDATE_SOURCES[0])

    respond({"tag_name": f"v{cur}"})
    p._fetch_update()
    check("同版本=已是最新", p._update_state["status"], "latest")

    respond({"tag_name": f"v{older}"})
    p._fetch_update()
    check("旧版本不提示", p._update_state["status"], "latest")

    _restore_urlopen()


def test_open_link_guards():
    p = make_plugin()
    check("没有链接时返回 False", Plugin.open_update_link(p), False)


def main() -> int:
    test_version_key()
    test_is_newer()
    test_extract_update()
    test_settings_validation()
    test_parse_source_list()
    test_source_selection()
    test_settings_accept_multiple()
    test_state_payload()
    test_save_update_settings()
    test_fetch_failures()
    test_fetch_success_states()
    test_open_link_guards()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())