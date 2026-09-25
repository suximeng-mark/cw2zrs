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

    // 派生数据只算一次，供多个绑定复用：
    // tomorrow=明日预告；columnRows*=两列对齐的行数据（紧凑每人一行 / 普通按岗位）
    property var tomorrow: (root.duty && root.duty.tomorrow) ? root.duty.tomorrow : null
    property var columnRowsPerson: root.duty ? root.columnRows(true) : []
    property var columnRowsGrouped: root.duty ? root.columnRows(false) : []

    text: qsTr("今日值日生")

    // 四个区域字号由设置页配置（未加载时用默认值）
    function fGroup() { return root.duty ? root.duty.fontGroup : 12 }
    function fMeta()  { return root.duty ? root.duty.fontMeta  : 12 }
    function fName()  { return root.duty ? root.duty.fontName  : 14 }
    function fTask()  { return root.duty ? root.duty.fontTask  : 14 }

    // 手动轮换偏移（_manual_offset）不为 0 时的兜底恢复入口：
    // 普通模式底部的「重置」按钮在紧凑模式下不显示，这里补一个
    function offsetActive() {
        return !!root.duty && root.duty.offset !== 0
    }

    function offsetText() {
        if (!root.duty || !root.duty.offset) return ""
        return qsTr("已手动调整 %1 组，点此恢复自动轮换").arg(Math.abs(root.duty.offset))
    }

    function resetOffset() {
        if (root.backend) root.backend.reset_group()
    }

    // 组件显隐由设置页配置（缺省显示）
    function showGroup() { return root.duty ? (root.duty.showGroup !== false) : true }
    function showName()  { return root.duty ? (root.duty.showName !== false) : true }
    function showTask()  { return root.duty ? (root.duty.showTask !== false) : true }
    function showMeta()  { return root.duty ? (root.duty.showMeta !== false) : true }

    // 高度：普通模式 = 基件余量 + 头部 + 成员区 + 明日预告 + 按钮行；
    // 紧凑模式 = 基件余量 + 三行内容（均随字号变化）
    height: miniMode
            ? miniColumn.implicitHeight + 21
            : 82 + normalHeader.implicitHeight + memberArea.implicitHeight
              + tomorrowPreview.implicitHeight + buttonRow.implicitHeight
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
    // 紧凑模式明日预告行的宽度度量（含“明日”标签宽度）
    TextMetrics {
        id: tmMiniTomorrow
        font.pixelSize: root.fMeta()
        text: root.tomorrowMiniText()
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
        font.pixelSize: root.fMeta()
        text: root.longestRightText()
    }

    function miniWidth() {
        // 第一行：组名胶囊(+14) + 间距6 + 次数 +（间距6 + 假期徽标(+10)）
        // 各段按显隐设置累计，全隐藏时仅由成员区决定宽度
        var top = 0
        if (root.showGroup()) top += tmMiniGroup.width + 14 + 6
        if (root.showMeta()) top += tmMiniPeriod.width
        if (root.duty && root.duty.isHoliday)
            top += 6 + tmMiniHoliday.width + 10
        // 成员区：连接符样式合并为一行；两列模式 = 姓名列 + 间距 + 任务列
        var content
        if (root.pairStyle() === "columns")
            content = Math.max(top, tmColName.width + 8 + tmColTask.width)
        else
            content = Math.max(top, tmMiniPair.width)
        // 明日预告行：“明日”标签约 2 字 + 间距
        if (root.tomorrowVisible())
            content = Math.max(content, tmMiniTomorrow.width + 42)
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

    // ------------------------------------------------ 明日预告
    function tomorrowData() {
        return root.tomorrow
    }

    function tomorrowVisible() {
        return !!(root.duty && root.duty.showTomorrow && root.duty.tomorrow)
    }

    // 明日成员按当前配对样式拼成一行
    function tomorrowMembersText() {
        var t = root.tomorrowData()
        if (!t || !t.members || t.members.length === 0)
            return qsTr("（无值日生）")
        var labels = []
        for (var i = 0; i < t.members.length; i++)
            labels.push(root.pairLabel(t.members[i]))
        return labels.join("、")
    }

    // 紧凑模式第四行完整文本（供宽度度量与显示共用）
    function tomorrowMiniText() {
        var t = root.tomorrowData()
        if (!t) return ""
        var s = t.shortDate + " " + t.weekday + " " + t.groupName + " · " + root.tomorrowMembersText()
        if (t.isHoliday)
            s += "（" + (t.holidayName || qsTr("假期")) + "）"
        return s
    }

    // ------------------------------------------------ 姓名/任务配对
    function pairStyle() {
        return root.duty ? (root.duty.pairStyle || "paren") : "paren"
    }

    function dispNameOf(m) {
        if (!root.showName()) return ""
        var nm = (m.name && m.name.length > 0) ? m.name : qsTr("（未命名）")
        if (m.status === "absent") nm += qsTr("（假）")
        return nm
    }

    // 单个成员的“姓名↔任务”配对文字（连接符样式由 pairStyle 决定；
    // 姓名/职责可分别在设置中隐藏，二者皆隐藏时显示占位符）
    function pairLabel(m) {
        var nm = root.dispNameOf(m)
        var t = root.showTask() ? ((m.task && m.task.length > 0) ? m.task : "") : ""
        if (nm && t) {
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
        return nm || t || "—"
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
        var sets = [root.columnRowsPerson, root.columnRowsGrouped]
        for (var s = 0; s < sets.length; s++)
            for (var i = 0; i < sets[s].length; i++)
                if (sets[s][i].left.length > best.length) best = sets[s][i].left
        return best
    }

    function longestRightText() {
        if (!root.duty || !root.duty.members) return "—"
        var best = "—"
        var sets = [root.columnRowsPerson, root.columnRowsGrouped]
        for (var s = 0; s < sets.length; s++)
            for (var i = 0; i < sets[s].length; i++)
                if ((sets[s][i].right || "").length > best.length) best = sets[s][i].right
        return best
    }

    // 两列对齐模式的行数据：{left, right, isTask}
    // perPerson=true（紧凑模式）：每个成员一行；false 时按岗位布局决定
    // 姓名/职责显隐在此统一过滤，两侧皆空的行被丢弃
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
                if (m.task && root.showTask()) {
                    if (taskIndex[m.task] === undefined) {
                        taskIndex[m.task] = out.length
                        out.push({ left: m.task, right: nm, isTask: true })
                    } else if (nm) {
                        out[taskIndex[m.task]].right += "、" + nm
                    }
                } else if (nm) {
                    out.push({ left: nm, right: "—", isTask: false })
                }
            }
            return out
        }

        var rows = []
        for (var k = 0; k < ms.length; k++) {
            var mm = ms[k]
            var nm2 = root.dispNameOf(mm)
            var tk = root.showTask() ? ((mm.task && mm.task.length > 0) ? mm.task : "—") : ""
            if (!nm2 && !tk) continue
            rows.push({
                left: nm2 || "—",
                right: tk,
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
            var inlineText = root.pairedInlineText()
            if (!inlineText) return []
            return [{ inline: true, task: "", names: [inlineText] }]
        }

        var out = []
        var taskIndex = ({})
        for (var i = 0; i < ms.length; i++) {
            var m = ms[i]
            if (layout === "person") {
                // 每人一行，配对写法跟随所选连接符
                out.push({ inline: true, task: "", names: [root.pairLabel(m)] })
            } else if (m.task && root.showTask()) {
                var nm = root.dispNameOf(m)
                if (taskIndex[m.task] === undefined) {
                    taskIndex[m.task] = out.length
                    out.push({ inline: false, task: m.task, names: nm ? [nm] : [] })
                } else if (nm) {
                    out[taskIndex[m.task]].names.push(nm)
                }
            } else {
                var nm2 = root.dispNameOf(m)
                if (nm2) out.push({ inline: false, task: "", names: [nm2] })
            }
        }
        // 过滤空行（姓名职责皆隐藏的成员）
        return out.filter(function(r) {
            return r.task !== "" || r.names.length > 0
        })
    }

    function periodText() {
        if (!root.duty) return ""
        var n = root.duty.periodNumber
        var step = root.duty.slotDays || 1
        // 步长 > 1：两天（周）算一次值日，额外显示本档进度
        if (step > 1)
            return qsTr("第 %1 次（%2/%3）").arg(n).arg(root.duty.slotPosition || 1).arg(step)
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

            // 第一行：组名胶囊 + 次数 + 假期徽标（显隐由设置控制）
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Rectangle {
                    visible: root.showGroup()
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
                    visible: root.duty && root.showMeta()
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
                           ? root.columnRowsPerson : 0

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

            // 第三行：明日值日预告（与第二行成员区互斥排版）
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                visible: root.tomorrowVisible()

                Text {
                    text: qsTr("明日")
                    font.pixelSize: root.fMeta()
                    opacity: 0.5
                }
                Text {
                    text: root.tomorrowMiniText()
                    font.pixelSize: root.fMeta()
                    color: Theme.isDark()
                           ? Qt.alpha("#FFFFFF", 0.85)
                           : Qt.alpha("#000000", 0.75)
                    elide: Text.ElideRight
                    Layout.maximumWidth: root.miniMaxWidth - 48
                }
            }

            // 仅在手动偏移不为 0 时出现，避免常态占位
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                visible: root.offsetActive()

                DutyPillButton {
                    label: qsTr("重置轮换")
                    Layout.preferredWidth: 88
                    onClicked: root.resetOffset()
                }
                Text {
                    text: root.offsetText()
                    font.pixelSize: root.fMeta()
                    opacity: 0.6
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }

        // 紧凑模式不响应点击：此前点一下就会调 next_group() 累加 _manual_offset 并写盘，
        // 导致「只点了下部件，值日组就永久偏移了」。手动切组一律走普通模式底部的按钮。

        // ===== 普通模式：完整展开 =====
        RowLayout {
            id: normalHeader
            Layout.fillWidth: true
            spacing: 8
            visible: !root.miniMode

            Rectangle {
                visible: !root.miniMode && root.showGroup()
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
                visible: root.showMeta()
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
                       ? root.columnRowsGrouped : 0

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

        // 明日预告（普通模式）：独立浅色条，隐藏时不占高度
        Rectangle {
            id: tomorrowPreview
            Layout.fillWidth: true
            visible: !root.miniMode && root.tomorrowVisible()
            implicitHeight: visible ? tomorrowPreviewRow.implicitHeight + 12 : 0
            radius: 8
            color: Theme.isDark()
                   ? Qt.alpha("#FFFFFF", 0.06)
                   : Qt.alpha("#000000", 0.045)

            RowLayout {
                id: tomorrowPreviewRow
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                anchors.topMargin: 6
                anchors.bottomMargin: 6
                spacing: 8

                Text {
                    text: {
                        var t = root.tomorrowData()
                        return t ? qsTr("明日 %1 %2").arg(t.shortDate).arg(t.weekday) : ""
                    }
                    font.pixelSize: root.fMeta()
                    opacity: 0.65
                }

                // 明日组名：描边小胶囊
                Rectangle {
                    Layout.preferredHeight: Math.max(18, tomGroupNameText.implicitHeight + 6)
                    Layout.preferredWidth: tomGroupNameText.implicitWidth + 14
                    radius: height / 2
                    color: "transparent"
                    border.width: 1
                    border.color: Colors.proxy.primaryColor

                    Text {
                        id: tomGroupNameText
                        anchors.centerIn: parent
                        text: root.tomorrowData() ? root.tomorrowData().groupName : ""
                        font.pixelSize: root.fMeta()
                        color: Colors.proxy.primaryColor
                    }
                }

                // 明日恰逢假期时给出徽标
                Rectangle {
                    visible: root.tomorrowData() && root.tomorrowData().isHoliday
                    Layout.preferredHeight: Math.max(16, tomHolidayText.implicitHeight + 5)
                    Layout.preferredWidth: tomHolidayText.implicitWidth + 10
                    radius: height / 2
                    color: "#E5A100"

                    Text {
                        id: tomHolidayText
                        anchors.centerIn: parent
                        text: (root.tomorrowData() && root.tomorrowData().holidayName)
                              ? root.tomorrowData().holidayName : qsTr("假期")
                        color: "#FFFFFF"
                        font.pixelSize: Math.max(9, root.fMeta() - 1)
                    }
                }

                Text {
                    text: root.tomorrowMembersText()
                    font.pixelSize: root.fName()
                    color: Theme.isDark()
                           ? Qt.alpha("#FFFFFF", 0.85)
                           : Qt.alpha("#000000", 0.8)
                    elide: Text.ElideRight
                    Layout.fillWidth: true
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
