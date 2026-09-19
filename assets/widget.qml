import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Theme

Widget {
    id: root

    property var duty: null
    property var rows: []
    property real miniMaxWidth: 360

    text: qsTr("今日值日生")

    // 四个区域字号由设置页配置（未加载时用默认值）
    function fGroup() { return root.duty ? root.duty.fontGroup : 12 }
    function fMeta()  { return root.duty ? root.duty.fontMeta  : 12 }
    function fName()  { return root.duty ? root.duty.fontName  : 14 }
    function fTask()  { return root.duty ? root.duty.fontTask  : 14 }

    // 高度：普通模式 = 基件余量 + 头部 + 成员区 + 按钮行；
    // 紧凑模式 = 基件余量 + 三行内容（均随字号变化）
    height: miniMode
            ? miniColumn.implicitHeight + 21
            : 82 + normalHeader.implicitHeight + memberArea.implicitHeight + buttonRow.implicitHeight
    implicitWidth: miniMode ? root.miniWidth() : 250

    // 紧凑模式三行布局的宽度度量
    TextMetrics {
        id: tmMiniGroup
        font.pixelSize: root.fGroup()
        font.weight: Font.DemiBold
        text: root.duty ? root.duty.groupName : ""
    }
    TextMetrics {
        id: tmMiniPeriod
        font.pixelSize: root.fMeta()
        text: root.periodText()
    }
    TextMetrics {
        id: tmMiniHoliday
        font.pixelSize: root.fMeta()
        text: (root.duty && root.duty.holidayName) ? root.duty.holidayName : qsTr("假期中")
    }
    TextMetrics {
        id: tmMiniPair
        font.pixelSize: root.fName()
        font.weight: Font.DemiBold
        text: root.pairedInlineText()
    }
    // 两列对齐时左列（姓名）宽度
    TextMetrics {
        id: tmColName
        font.pixelSize: root.fName()
        font.weight: Font.DemiBold
        text: root.longestLeftText()
    }
    // 两列对齐时右列（任务）宽度
    TextMetrics {
        id: tmColTask
        font.pixelSize: root.fTask()
        text: root.longestRightText()
    }

    function miniWidth() {
        // 第一行：组名胶囊(+14) + 间距6 + 周期 +（间距6 + 假期徽标(+10)）
        var top = tmMiniGroup.width + 14 + 6 + tmMiniPeriod.width
        if (root.duty && root.duty.isHoliday)
            top += 6 + tmMiniHoliday.width + 10
        // 成员区：连接符合并为一行；两列模式 = 姓名列 + 间距 + 任务列
        var content
        if (root.pairStyle() === "columns")
            content = Math.max(top, tmColName.width + 8 + tmColTask.width)
        else
            content = Math.max(top, tmMiniPair.width)
        // +48 与基件 Widget 的内容边距算法保持一致
        return Math.max(150, Math.min(root.miniMaxWidth, content + 48))
    }

    onBackendChanged: refresh()
    Component.onCompleted: Qt.callLater(refresh)

    Connections {
        target: root.backend
        function onDutyChanged() { refresh() }
    }

    function refresh() {
        if (!root.backend) return
        root.duty = root.backend.get_today_duty()
        root.rows = root.displayRows()
    }

    // ------------------------------------------------ 姓名/任务配对
    function pairStyle() {
        return root.duty ? (root.duty.pairStyle || "paren") : "paren"
    }

    function dispNameOf(m) {
        var nm = (m.name && m.name.length > 0) ? m.name : qsTr("（未命名）")
        if (m.status === "absent") nm += qsTr("（假）")
        return nm
    }

    // 单个成员的“姓名↔任务”配对文字（连接符样式由 pairStyle 决定）
    function pairLabel(m) {
        var nm = root.dispNameOf(m)
        var t = (m.task && m.task.length > 0) ? m.task : ""
        if (!t) return nm
        switch (root.pairStyle()) {
        case "dot":
            return nm + "·" + t
        case "taskfirst":
            return t + "：" + nm
        case "paren":
        default:
            return nm + qsTr("（%1）").arg(t)
        }
    }

    // 连接符样式下，紧凑模式/普通合并一行的整行文本
    function pairedInlineText() {
        if (!root.duty || !root.duty.members || root.duty.members.length === 0)
            return qsTr("（无值日生）")
        var labels = []
        for (var i = 0; i < root.duty.members.length; i++)
            labels.push(root.pairLabel(root.duty.members[i]))
        return labels.join("、")
    }

    function longestLeftText() {
        if (!root.duty || !root.duty.members) return ""
        var best = ""
        var sets = [root.columnRows(false), root.columnRows(true)]
        for (var s = 0; s < sets.length; s++)
            for (var i = 0; i < sets[s].length; i++)
                if (sets[s][i].left.length > best.length) best = sets[s][i].left
        return best
    }

    function longestRightText() {
        if (!root.duty || !root.duty.members) return "—"
        var best = "—"
        var sets = [root.columnRows(false), root.columnRows(true)]
        for (var s = 0; s < sets.length; s++)
            for (var i = 0; i < sets[s].length; i++)
                if ((sets[s][i].right || "").length > best.length) best = sets[s][i].right
        return best
    }

    // 两列对齐模式的行数据：{left, right, isTask}
    // perPerson=true（紧凑模式）：每个成员一行；false 时按岗位布局决定
    function columnRows(perPerson) {
        if (!root.duty || !root.duty.members) return []
        var layout = root.duty.memberLayout || "task"
        var ms = root.duty.members

        if (!perPerson && layout === "task") {
            var out = []
            var taskIndex = ({})
            for (var i = 0; i < ms.length; i++) {
                var m = ms[i]
                var nm = root.dispNameOf(m)
                if (m.task) {
                    if (taskIndex[m.task] === undefined) {
                        taskIndex[m.task] = out.length
                        out.push({ left: m.task, right: nm, isTask: true })
                    } else {
                        out[taskIndex[m.task]].right += "、" + nm
                    }
                } else {
                    out.push({ left: nm, right: "—", isTask: false })
                }
            }
            return out
        }

        var rows = []
        for (var k = 0; k < ms.length; k++) {
            var mm = ms[k]
            rows.push({
                left: root.dispNameOf(mm),
                right: (mm.task && mm.task.length > 0) ? mm.task : "—",
                isTask: false
            })
        }
        return rows
    }

    // 普通模式成员行构建（非两列模式）：
    // inline=全部合并一行；person=每人一行；task=按岗位归并行
    function displayRows() {
        if (!root.duty || !root.duty.members) return []
        if (root.pairStyle() === "columns") return []
        var layout = root.duty.memberLayout || "task"
        var ms = root.duty.members

        if (layout === "inline") {
            return [{ inline: true, task: "", names: [root.pairedInlineText()] }]
        }

        var out = []
        var taskIndex = ({})
        for (var i = 0; i < ms.length; i++) {
            var m = ms[i]
            if (layout === "person") {
                // 每人一行，配对写法跟随所选连接符
                out.push({ inline: true, task: "", names: [root.pairLabel(m)] })
            } else if (m.task) {
                var nm = root.dispNameOf(m)
                if (taskIndex[m.task] === undefined) {
                    taskIndex[m.task] = out.length
                    out.push({ inline: false, task: m.task, names: [nm] })
                } else {
                    out[taskIndex[m.task]].names.push(nm)
                }
            } else {
                out.push({ inline: false, task: "", names: [root.dispNameOf(m)] })
            }
        }
        return out
    }

    function periodText() {
        if (!root.duty) return ""
        var n = root.duty.periodNumber
        if (root.duty.rotationMode === "daily") return qsTr("第 %1 天").arg(n)
        if (root.duty.rotationMode === "workday") return qsTr("第 %1 轮").arg(n)
        return qsTr("第 %1 周").arg(n)
    }

    actions: Subtitle {
        text: root.duty ? root.duty.date : ""
        visible: !root.miniMode
    }

    component DutyPillButton: Rectangle {
        id: pill
        property string label: ""
        property bool accent: false
        signal clicked()

        Layout.preferredHeight: Math.max(28, root.fGroup() * 2 + 2)
        radius: pill.height / 2
        opacity: pill.enabled ? 1.0 : 0.4
        color: pill.accent
               ? Colors.proxy.primaryColor
               : (Theme.isDark() ? Qt.alpha("#FFFFFF", 0.1) : Qt.alpha("#000000", 0.06))

        Text {
            anchors.centerIn: parent
            text: pill.label
            font.pixelSize: root.fGroup()
            color: pill.accent
                   ? "#FFFFFF"
                   : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
        }

        TapHandler {
            enabled: pill.enabled
            onTapped: pill.clicked()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 6

        // ===== 紧凑模式：三行显示，宽度随内容变化 =====
        ColumnLayout {
            id: miniColumn
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 4
            visible: root.miniMode

            // 第一行：组名胶囊 + 周期 + 假期徽标
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Rectangle {
                    Layout.preferredHeight: Math.max(18, miniGroupText.implicitHeight + 8)
                    Layout.preferredWidth: miniGroupText.implicitWidth + 14
                    radius: height / 2
                    color: Colors.proxy.primaryColor

                    Text {
                        id: miniGroupText
                        anchors.centerIn: parent
                        text: root.duty ? root.duty.groupName : "—"
                        color: "#FFFFFF"
                        font.pixelSize: root.fGroup()
                        font.weight: Font.DemiBold
                    }
                }

                Text {
                    text: root.periodText()
                    font.pixelSize: root.fMeta()
                    opacity: 0.55
                    visible: root.duty
                }

                Rectangle {
                    visible: root.duty && root.duty.isHoliday
                    Layout.preferredHeight: Math.max(14, miniHolidayText.implicitHeight + 5)
                    Layout.preferredWidth: miniHolidayText.implicitWidth + 10
                    radius: height / 2
                    color: "#E5A100"

                    Text {
                        id: miniHolidayText
                        anchors.centerIn: parent
                        text: (root.duty && root.duty.holidayName)
                              ? root.duty.holidayName : qsTr("假期中")
                        color: "#FFFFFF"
                        font.pixelSize: root.fMeta()
                    }
                }

                Item { Layout.fillWidth: true }
            }

            // 第二行：姓名与任务一一对应（连接符样式合并为一行）
            Text {
                visible: root.pairStyle() !== "columns"
                text: root.pairedInlineText()
                font.pixelSize: root.fName()
                font.weight: Font.DemiBold
                color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                elide: Text.ElideRight
                Layout.maximumWidth: root.miniMaxWidth - 48
            }

            // 两列对齐：每个成员一行，左姓名右任务
            ColumnLayout {
                Layout.maximumWidth: root.miniMaxWidth - 48
                visible: root.pairStyle() === "columns"
                spacing: 2

                Repeater {
                    model: root.pairStyle() === "columns"
                           ? root.columnRows(true) : 0

                    delegate: RowLayout {
                        spacing: 8

                        Text {
                            text: modelData.left
                            font.pixelSize: root.fName()
                            font.weight: Font.DemiBold
                            color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                            elide: Text.ElideRight
                            Layout.preferredWidth: tmColName.width
                        }

                        Text {
                            text: modelData.right
                            font.pixelSize: root.fTask()
                            color: Theme.isDark()
                                   ? Qt.alpha("#FFFFFF", 0.6)
                                   : Qt.alpha("#000000", 0.55)
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        // 点击紧凑模式切换下一组
        TapHandler {
            enabled: root.miniMode && root.backend
            onTapped: if (root.backend) root.backend.next_group()
        }

        // ===== 普通模式：完整展开 =====
        RowLayout {
            id: normalHeader
            Layout.fillWidth: true
            spacing: 8
            visible: !root.miniMode

            Rectangle {
                Layout.preferredHeight: Math.max(22, groupText.implicitHeight + 10)
                Layout.preferredWidth: groupText.implicitWidth + 22
                radius: height / 2
                color: Colors.proxy.primaryColor

                Text {
                    id: groupText
                    anchors.centerIn: parent
                    text: root.duty ? root.duty.groupName : "—"
                    color: "#FFFFFF"
                    font.pixelSize: root.fGroup()
                    font.weight: Font.DemiBold
                }
            }

            Text {
                text: root.periodText()
                font.pixelSize: root.fMeta()
                opacity: 0.6
            }

            Rectangle {
                visible: root.duty && root.duty.isHoliday
                Layout.preferredHeight: Math.max(18, holidayBadgeText.implicitHeight + 8)
                Layout.preferredWidth: holidayBadgeText.implicitWidth + 14
                radius: height / 2
                color: "#E5A100"

                Text {
                    id: holidayBadgeText
                    anchors.centerIn: parent
                    text: root.duty && root.duty.holidayName
                          ? root.duty.holidayName : qsTr("假期中")
                    color: "#FFFFFF"
                    font.pixelSize: root.fMeta()
                }
            }

            Rectangle {
                visible: root.duty && root.duty.switched
                Layout.preferredHeight: Math.max(18, switchedBadgeText.implicitHeight + 8)
                Layout.preferredWidth: switchedBadgeText.implicitWidth + 14
                radius: height / 2
                color: "transparent"
                border.width: 1
                border.color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.4) : Qt.alpha("#000000", 0.3)

                Text {
                    id: switchedBadgeText
                    anchors.centerIn: parent
                    text: qsTr("已调换")
                    font.pixelSize: root.fMeta()
                    color: Theme.isDark()
                           ? Qt.alpha("#FFFFFF", 0.7)
                           : Qt.alpha("#000000", 0.6)
                }
            }

            Item { Layout.fillWidth: true }
        }

        // 成员区：排列方式由设置控制（inline/task/person），
        // 配对样式为 columns 时左右两列对齐；部件高度绑定其 implicitHeight
        ColumnLayout {
            id: memberArea
            Layout.fillWidth: true
            spacing: 4
            visible: !root.miniMode

            // 非两列模式：按行（连接符样式/岗位归并）
            Repeater {
                model: root.pairStyle() !== "columns" ? root.rows : 0

                delegate: RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        visible: !modelData.inline && modelData.task !== ""
                        text: modelData.task ? modelData.task + "：" : ""
                        font.pixelSize: root.fTask()
                        font.weight: Font.DemiBold
                        color: Colors.proxy.primaryColor
                    }

                    Text {
                        text: modelData.names.join("、")
                        font.pixelSize: root.fName()
                        font.weight: (!modelData.inline && modelData.task !== "")
                                     ? Font.Normal : Font.DemiBold
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                    }

                    Item { Layout.fillWidth: true }
                }
            }

            // 两列模式：左列任务/姓名、右列姓名/任务，纵向一一对应
            Repeater {
                model: root.pairStyle() === "columns"
                       ? root.columnRows(false) : 0

                delegate: RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: modelData.left
                        font.pixelSize: modelData.isTask ? root.fTask() : root.fName()
                        font.weight: Font.DemiBold
                        color: modelData.isTask
                               ? Colors.proxy.primaryColor
                               : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
                        elide: Text.ElideRight
                        Layout.preferredWidth: Math.max(tmColName.width, tmColTask.width)
                    }

                    Text {
                        text: modelData.right
                        font.pixelSize: modelData.isTask ? root.fName() : root.fTask()
                        font.weight: Font.Normal
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: Theme.isDark()
                               ? Qt.alpha("#FFFFFF", modelData.isTask ? 1.0 : 0.6)
                               : Qt.alpha("#000000", modelData.isTask ? 1.0 : 0.55)
                    }

                    Item { Layout.fillWidth: true }
                }
            }
        }

        Item { Layout.fillHeight: true; visible: !root.miniMode }

        RowLayout {
            id: buttonRow
            Layout.fillWidth: true
            spacing: 6
            visible: !root.miniMode

            DutyPillButton {
                label: qsTr("上一组")
                Layout.fillWidth: true
                onClicked: if (root.backend) root.backend.prev_group()
            }

            DutyPillButton {
                label: qsTr("重置")
                Layout.fillWidth: true
                enabled: root.duty ? root.duty.offset !== 0 : false
                onClicked: if (root.backend) root.backend.reset_group()
            }

            DutyPillButton {
                label: qsTr("下一组")
                accent: true
                Layout.fillWidth: true
                onClicked: if (root.backend) root.backend.next_group()
            }
        }
    }
}
