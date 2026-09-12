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

    height: miniMode ? 82 : (132 + root.rows.length * 28)
    implicitWidth: miniMode ? root.miniWidth() : 250

    // 紧凑模式三行布局的宽度度量
    TextMetrics {
        id: tmMiniGroup
        font.pixelSize: 10
        font.weight: Font.DemiBold
        text: root.duty ? root.duty.groupName : ""
    }
    TextMetrics {
        id: tmMiniPeriod
        font.pixelSize: 10
        text: root.periodText()
    }
    TextMetrics {
        id: tmMiniHoliday
        font.pixelSize: 9
        text: (root.duty && root.duty.holidayName) ? root.duty.holidayName : qsTr("假期中")
    }
    TextMetrics {
        id: tmMiniMembers
        font.pixelSize: 13
        font.weight: Font.DemiBold
        text: root.membersInlineText()
    }
    TextMetrics {
        id: tmMiniTasks
        font.pixelSize: 12
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

    // 按岗位（task）把成员归并成行；无岗位的成员每人独占一行
    function displayRows() {
        if (!root.duty || !root.duty.members) return []
        var out = []
        var taskIndex = ({})
        var ms = root.duty.members
        for (var i = 0; i < ms.length; i++) {
            var m = ms[i]
            var nm = (m.name && m.name.length > 0) ? m.name : qsTr("（未命名）")
            if (m.status === "absent") nm += qsTr("（假）")
            if (m.task) {
                if (taskIndex[m.task] === undefined) {
                    taskIndex[m.task] = out.length
                    out.push({ task: m.task, names: [nm] })
                } else {
                    out[taskIndex[m.task]].names.push(nm)
                }
            } else {
                out.push({ task: "", names: [nm] })
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

        Layout.preferredHeight: 28
        radius: 14
        opacity: pill.enabled ? 1.0 : 0.4
        color: pill.accent
               ? Colors.proxy.primaryColor
               : (Theme.isDark() ? Qt.alpha("#FFFFFF", 0.1) : Qt.alpha("#000000", 0.06))

        Text {
            anchors.centerIn: parent
            text: pill.label
            font.pixelSize: 12
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

        // ===== 紧凑模式：两行显示，宽度随内容变化 =====
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 4
            visible: root.miniMode

            // 第一行：组名胶囊 + 周期 + 假期徽标
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Rectangle {
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: miniGroupText.implicitWidth + 14
                    radius: 9
                    color: Colors.proxy.primaryColor

                    Text {
                        id: miniGroupText
                        anchors.centerIn: parent
                        text: root.duty ? root.duty.groupName : "—"
                        color: "#FFFFFF"
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }
                }

                Text {
                    text: root.periodText()
                    font.pixelSize: 10
                    opacity: 0.55
                    visible: root.duty
                }

                Rectangle {
                    visible: root.duty && root.duty.isHoliday
                    Layout.preferredHeight: 14
                    Layout.preferredWidth: miniHolidayText.implicitWidth + 10
                    radius: 7
                    color: "#E5A100"

                    Text {
                        id: miniHolidayText
                        anchors.centerIn: parent
                        text: (root.duty && root.duty.holidayName)
                              ? root.duty.holidayName : qsTr("假期中")
                        color: "#FFFFFF"
                        font.pixelSize: 9
                    }
                }

                Item { Layout.fillWidth: true }
            }

            // 第二行：全部成员姓名（宽度可变，超长时在部件最大宽度内省略）
            Text {
                text: root.membersInlineText()
                font.pixelSize: 13
                font.weight: Font.DemiBold
                color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                elide: Text.ElideRight
                Layout.maximumWidth: root.miniMaxWidth - 48
            }

            // 第三行：全部成员任务（与第二行按位置一一对应）
            Text {
                text: root.tasksInlineText()
                font.pixelSize: 12
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
            Layout.fillWidth: true
            spacing: 8
            visible: !root.miniMode

            Rectangle {
                Layout.preferredHeight: 22
                Layout.preferredWidth: groupText.implicitWidth + 22
                radius: 11
                color: Colors.proxy.primaryColor

                Text {
                    id: groupText
                    anchors.centerIn: parent
                    text: root.duty ? root.duty.groupName : "—"
                    color: "#FFFFFF"
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }

            Text {
                text: root.periodText()
                font.pixelSize: 12
                opacity: 0.6
            }

            Rectangle {
                visible: root.duty && root.duty.isHoliday
                Layout.preferredHeight: 18
                Layout.preferredWidth: holidayBadgeText.implicitWidth + 14
                radius: 9
                color: "#E5A100"

                Text {
                    id: holidayBadgeText
                    anchors.centerIn: parent
                    text: root.duty && root.duty.holidayName
                          ? root.duty.holidayName : qsTr("假期中")
                    color: "#FFFFFF"
                    font.pixelSize: 10
                }
            }

            Rectangle {
                visible: root.duty && root.duty.switched
                Layout.preferredHeight: 18
                Layout.preferredWidth: switchedBadgeText.implicitWidth + 14
                radius: 9
                color: "transparent"
                border.width: 1
                border.color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.4) : Qt.alpha("#000000", 0.3)

                Text {
                    id: switchedBadgeText
                    anchors.centerIn: parent
                    text: qsTr("已调换")
                    font.pixelSize: 10
                    color: Theme.isDark()
                           ? Qt.alpha("#FFFFFF", 0.7)
                           : Qt.alpha("#000000", 0.6)
                }
            }

            Item { Layout.fillWidth: true }
        }

        Repeater {
            model: root.rows

            delegate: RowLayout {
                Layout.fillWidth: true
                spacing: 8
                visible: !root.miniMode

                Text {
                    visible: modelData.task !== ""
                    text: modelData.task ? modelData.task + "：" : ""
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    color: Colors.proxy.primaryColor
                }

                Text {
                    text: modelData.names.join("、")
                    font.pixelSize: modelData.task !== "" ? 14 : 15
                    font.weight: modelData.task !== "" ? Font.Normal : Font.DemiBold
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                    color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                }

                Item { Layout.fillWidth: true }
            }
        }

        Item { Layout.fillHeight: true; visible: !root.miniMode }

        RowLayout {
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
