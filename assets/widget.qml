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
        id: tmMiniMembers
        font.pixelSize: root.fName()
        font.weight: Font.DemiBold
        text: root.membersInlineText()
    }
    TextMetrics {
        id: tmMiniTasks
        font.pixelSize: root.fTask()
        text: root.tasksInlineText()
    }

    function miniWidth() {
        // 第一行：组名胶囊(+14) + 间距6 + 周期 +（间距6 + 假期徽标(+10)）
        var top = tmMiniGroup.width + 14 + 6 + tmMiniPeriod.width
        if (root.duty && root.duty.isHoliday)
            top += 6 + tmMiniHoliday.width + 10
        // 第二行：全部成员名，第三行：全部任务名
        var content = Math.max(top, tmMiniMembers.width, tmMiniTasks.width)
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

    // 普通模式成员行构建：
    // inline=全部合并一行（姓名后括注岗位）；task=按岗位归并行；person=每人一行
    function displayRows() {
        if (!root.duty || !root.duty.members) return []
        var layout = root.duty.memberLayout || "task"
        var ms = root.duty.members

        function dispName(m) {
            var nm = (m.name && m.name.length > 0) ? m.name : qsTr("（未命名）")
            if (m.status === "absent") nm += qsTr("（假）")
            return nm
        }

        if (layout === "inline") {
            var labels = []
            for (var k = 0; k < ms.length; k++) {
                var label = dispName(ms[k])
                if (ms[k].task) label += qsTr("（%1）").arg(ms[k].task)
                labels.push(label)
            }
            return [{
                inline: true,
                task: "",
                names: [labels.length > 0 ? labels.join("、") : qsTr("（无值日生）")]
            }]
        }

        var out = []
        var taskIndex = ({})
        for (var i = 0; i < ms.length; i++) {
            var m = ms[i]
            var nm = dispName(m)
            if (layout === "person") {
                out.push({ inline: false, task: m.task || "", names: [nm] })
            } else if (m.task) {
                if (taskIndex[m.task] === undefined) {
                    taskIndex[m.task] = out.length
                    out.push({ inline: false, task: m.task, names: [nm] })
                } else {
                    out[taskIndex[m.task]].names.push(nm)
                }
            } else {
                out.push({ inline: false, task: "", names: [nm] })
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

    function membersInlineText() {
        if (!root.duty || !root.duty.members || root.duty.members.length === 0)
            return qsTr("（无值日生）")
        var names = []
        for (var i = 0; i < root.duty.members.length; i++) {
            var n = root.duty.members[i].name
            var s = (n && n.length > 0) ? n : qsTr("未命名")
            if (root.duty.members[i].status === "absent") s += qsTr("（假）")
            names.push(s)
        }
        return names.join("、")
    }

    function tasksInlineText() {
        if (!root.duty || !root.duty.members || root.duty.members.length === 0)
            return ""
        var tasks = []
        for (var i = 0; i < root.duty.members.length; i++) {
            var t = root.duty.members[i].task
            var s = (t && t.length > 0) ? t : "—"
            if (root.duty.members[i].status === "absent") s += qsTr("（假）")
            tasks.push(s)
        }
        return tasks.join("、")
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

            // 第二行：全部成员姓名（宽度可变，超长时在部件最大宽度内省略）
            Text {
                text: root.membersInlineText()
                font.pixelSize: root.fName()
                font.weight: Font.DemiBold
                color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                elide: Text.ElideRight
                Layout.maximumWidth: root.miniMaxWidth - 48
            }

            // 第三行：全部成员任务（与第二行按位置一一对应）
            Text {
                text: root.tasksInlineText()
                font.pixelSize: root.fTask()
                color: Theme.isDark()
                       ? Qt.alpha("#FFFFFF", 0.6)
                       : Qt.alpha("#000000", 0.55)
                elide: Text.ElideRight
                Layout.maximumWidth: root.miniMaxWidth - 48
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
        // 用独立 ColumnLayout 承载，部件高度绑定其 implicitHeight
        ColumnLayout {
            id: memberArea
            Layout.fillWidth: true
            spacing: 4
            visible: !root.miniMode

            Repeater {
                model: root.rows

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
