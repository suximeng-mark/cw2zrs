# -*- coding: utf-8 -*-
"""更新检查的跨线程信号回归测试（必须用**真实** PySide6）。

为什么这个文件单独存在、且不 import test_rotation：
后者会把整个 PySide6.QtCore 换成假模块，而本用例要验证的恰恰是
「后台线程的请求结果能不能真的送达主线程」——假的 Qt 测不出来。

它防住的是 v1.12.0 的一个真实缺陷：_fetch_update 结尾原本用
    QTimer.singleShot(0, self.updateReady.emit)
把结果抛回主线程，但 QTimer.singleShot 在**没有事件循环的线程**里
调用永远不会触发（已实测），界面会永远停在「检查中…」。

运行方式：
    python tests/test_update_signal.py
"""

import json
import sys
import threading
import types
import urllib.request
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 只桩 ClassWidgets.SDK；PySide6 保持真实
sdk_mod = types.ModuleType("ClassWidgets.SDK")


class ConfigBaseModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class CW2Plugin(QObject):
    def __init__(self, api=None):
        super().__init__()
        self.api = api


class PluginAPI:
    pass


sdk_mod.ConfigBaseModel = ConfigBaseModel
sdk_mod.CW2Plugin = CW2Plugin
sdk_mod.PluginAPI = PluginAPI
sys.modules["ClassWidgets.SDK"] = sdk_mod
import ClassWidgets  # noqa: E402,F401  让上面的子模块挂载生效

import main as m  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got={got!r} want={want!r}")


# Qt 只允许一个 QCoreApplication 单例，整个文件共用
APP = QCoreApplication([])


def make_plugin(app=None):
    """构造一个真正初始化过 QObject 的 Plugin（不走 __init__ 的 QTimer 依赖）。"""
    p = m.Plugin.__new__(m.Plugin)   # QObject 子类不能用 object.__new__
    QObject.__init__(p)
    p._settings = dict(m.DEFAULT_SETTINGS)
    p._update_cancelled = threading.Event()
    p._update_state = {
        "status": "idle", "latest": "", "current": "",
        "download": "", "page": "", "msg": "",
    }
    p._schedule_config_flush = lambda: None
    return p


def wait_for(predicate, timeout_ms=4000):
    """跑事件循环直到 predicate 为真或超时。"""
    steps = 40
    for _ in range(steps):
        if predicate():
            return True
        QTimer.singleShot(timeout_ms // steps, lambda: None)
        APP.processEvents()
        threading.Event().wait(timeout_ms / steps / 1000.0)
    return predicate()


def fake_urlopen(payload):
    class _Resp:
        def read(self, n=-1):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    urllib.request.urlopen = lambda *a, **k: _Resp()


def test_signal_arrives_from_worker():
    p = make_plugin()
    received = []
    p.updateReady.connect(lambda: received.append(p._update_state["status"]))

    fake_urlopen({"tag_name": "v99.0.0",
                  "html_url": "https://example/page",
                  "assets": [{"browser_download_url": "https://example/p.cwplugin"}]})

    # 模拟 check_update：起后台线程跑 _fetch_update
    p._update_cancelled.clear()
    p._update_state = {"status": "checking", "latest": "", "current": p.current_version(),
                       "download": "", "page": "", "msg": ""}
    t = threading.Thread(target=p._fetch_update, args=("https://example/api",), daemon=True)
    t.start()
    t.join(5)

    ok = wait_for(lambda: len(received) > 0)
    check("后台线程的结果送达主线程", ok, True)
    check("信号带回状态为 available", received and received[0] == "available", True)
    check("版本号已解析", p._update_state["latest"], "99.0.0")
    check("下载直链已解析", p._update_state["download"], "https://example/p.cwplugin")


def test_cancelled_thread_does_not_emit():
    """卸载后到达的请求不能往已销毁的 QObject 上 emit。"""
    p = make_plugin()
    received = []
    p.updateReady.connect(lambda: received.append(1))

    fake_urlopen({"tag_name": "v99.0.1"})
    p._update_cancelled.set()          # 模拟卸载已发生
    p._fetch_update("https://example/api")
    check("已取消时不发信号", len(received), 0)
    check("状态仍然写回了（供下次读取）", p._update_state["latest"], "99.0.1")


class Emitter(QObject):
    done = Signal()


def test_emit_from_worker_needs_no_event_loop():
    """直接断言那条教训：工作线程里 singleShot 不会触发，信号会。"""
    hits = {"singleShot": False, "signal": False}

    e = Emitter()
    e.done.connect(lambda: hits.__setitem__("signal", True))

    def worker():
        # 这正是 v1.12.0 原来的写法：工作线程里排一个 0ms 定时器
        QTimer.singleShot(0, lambda: hits.__setitem__("singleShot", True))
        e.done.emit()

    t = threading.Thread(target=worker)
    t.start()
    t.join(3)
    wait_for(lambda: hits["signal"])
    check("工作线程里的 singleShot 确实不触发（所以不能这么用）",
          hits["singleShot"], False)
    check("QObject 信号从工作线程发出可达", hits["signal"], True)


def main() -> int:
    test_signal_arrives_from_worker()
    test_cancelled_thread_does_not_emit()
    test_emit_from_worker_needs_no_event_loop()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())