# -*- coding: utf-8 -*-
"""QML 列表刷新机制的回归测试（需要真实 PySide6）。

背景（v2.0.2 修复的真实缺陷）
--------------------------------
「人员设置」页点「+ 新增成员」没反应。原因是那批性能优化把
`model: root.membersOfCurrent()` 改成了派生属性 `model: root.currentMembers`，
而 `membersOfCurrent()` 返回的是**同一个数组对象**：

    g.members.push(...)          # 原地改，对象身份不变
    root.groupsData = slice()    # 触发 currentMembers 重新求值
    root.bumpEdit()

`currentMembers` 重新求值后拿到的仍是同一个 QVariant，Qt 判定「值没变」，
于是**不发变更通知**，Repeater 自然不重建。优化前 `model:` 直接调函数，
每次求值都会触发刷新，所以那时是好的——这是优化引入的回归。

同一个文件里还有第二部分：静态检查 settings.qml 的增删成员函数，
确保它们不再原地改动 members 数组（否则这个坑会再踩一次）。

运行方式：
    python tests/test_qml_model_identity.py
"""

import re
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(__file__).resolve().parents[1]

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got={got!r} want={want!r}")


# 与 settings.qml 里「当前组成员」完全同构的最小复现
QML = '''
import QtQuick
Item {
    id: root
    width: 200; height: 200
    property var groups: [{ name: "g1", members: [{ name: "a", task: "t" }] }]
    property int editRev: 0
    property int rowCount: 0
    property int groupIndex: 0

    function membersOfCurrent() { root.editRev; return root.groups[root.groupIndex].members }
    property var currentMembers: root.membersOfCurrent()

    function groupAt(gi) { return root.groups[gi] || null }
    function bumpEdit() { root.editRev++ }
    function reset() { root.groups = [{ name: "g1", members: [{ name: "a", task: "t" }] }]; root.editRev = 0 }

    // 修复后的写法：换一个新的数组对象
    function replaceMembers(gi, members) {
        var g = root.groups[gi]
        if (!g) return false
        g.members = members
        root.groups = root.groups.slice()
        root.bumpEdit()
        return true
    }
    function addMember() {
        var g = root.groupAt(root.groupIndex)
        if (!g) return
        var list = (g.members || []).slice()
        list.push({ name: "", task: "" })
        root.replaceMembers(root.groupIndex, list)
    }
    function removeMember(i) {
        var g = root.groupAt(root.groupIndex)
        var list = (g && g.members) || []
        if (!g || i < 0 || i >= list.length) return
        root.replaceMembers(root.groupIndex,
                            list.slice(0, i).concat(list.slice(i + 1)))
    }
    // invokeMethod 传不了参数，用固定下标的包装来驱动真实代码路径
    function removeFirst() { root.removeMember(0) }
    function removeTwice() { root.removeMember(0); root.removeMember(0) }

    // 旧写法（仅用于验证机制，不是插件里的代码）
    function addMemberInPlace() {
        var g = root.groupAt(root.groupIndex)
        if (!g) return
        g.members.push({ name: "", task: "" })
        root.groups = root.groups.slice()
        root.bumpEdit()
    }

    Repeater {
        model: root.currentMembers
        delegate: Item {
            width: 1; height: 1
            Component.onCompleted: root.rowCount++
            Component.onDestruction: root.rowCount--
        }
    }
}
'''


# engine / component 必须保持引用：出了作用域会被 GC，连带把 obj 析构掉
_KEEPALIVE = []


def build():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine = QQmlEngine()
    comp = QQmlComponent(engine)
    comp.setData(QML.encode("utf-8"), QUrl("file:///model_identity.qml"))
    obj = comp.create()
    if obj is None:
        raise SystemExit("QML 错误: " + str([e.toString() for e in comp.errors()]))
    _KEEPALIVE.extend([engine, comp, obj])
    return app, obj


def spin(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def call(obj, name):
    obj.metaObject().invokeMethod(obj, name)
    spin()


def test_mechanism():
    app, obj = build()
    spin()
    check("初始渲染出 1 行", obj.property("rowCount"), 1)

    call(obj, "reset")
    check("重置后 1 行", obj.property("rowCount"), 1)

    call(obj, "addMemberInPlace")
    check("原地 push 不会触发重建（这就是那个 bug 的成因）",
          obj.property("rowCount"), 1)

    call(obj, "reset")
    call(obj, "addMember")
    check("换成新数组后新增成员生效", obj.property("rowCount"), 2)

    call(obj, "addMember")
    check("连续再加一个", obj.property("rowCount"), 3)

    call(obj, "removeFirst")
    check("移除一个后行数回落", obj.property("rowCount"), 2)

    call(obj, "removeTwice")
    check("全部移除后为 0 行", obj.property("rowCount"), 0)

    call(obj, "addMember")
    check("删空后仍能新增", obj.property("rowCount"), 1)


def test_settings_qml_does_not_mutate_in_place():
    """静态守卫：settings.qml 的增删成员必须走 replaceMembers，不能原地改数组。"""
    src = (ROOT / "assets" / "settings.qml").read_text(encoding="utf-8")

    for fn in ("addMember", "removeMember", "importMembers"):
        m = re.search(rf"function {fn}\([^)]*\)\s*\{{(.*?)\n    \}}", src, re.S)
        check(f"找到 {fn} 定义", m is not None, True)
        if not m:
            continue
        body = m.group(1)
        check(f"{fn} 不再原地 push/splice",
              re.search(r"members\.(push|splice|pop|shift)\s*\(", body) is None, True)
        check(f"{fn} 走 replaceMembers", "replaceMembers(" in body, True)

    # setMemberField 必须保持原地改：它每次按键都调用，触发重建会让输入框失焦
    m = re.search(r"function setMemberField\([^)]*\)\s*\{(.*?)\n    \}", src, re.S)
    check("找到 setMemberField 定义", m is not None, True)
    if m:
        check("setMemberField 仍是原地赋值（避免输入框失焦）",
              ".members[mi][field] = value" in m.group(1), True)


def main() -> int:
    test_mechanism()
    test_settings_qml_does_not_mutate_in_place()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())