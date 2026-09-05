import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    width: 240
    height: contentColumn.height + 24

    // 主题检测（深色 / 浅色）
    readonly property bool isDark: Qt.application.styleHints
        ? Qt.application.styleHints.colorScheme === Qt.ColorScheme.Dark
        : false

    readonly property color cardColor: isDark ? "#2b2b2b" : "#ffffff"
    readonly property color textPrimary: isDark ? "#ffffff" : "#1a1a1a"
    readonly property color textSecondary: isDark ? "#b0b0b0" : "#666666"
    readonly property color borderColor: isDark ? "#444444" : "#e0e0e0"
    readonly property color accentColor: "#0078d4"

    Rectangle {
        id: card
        anchors.fill: parent
        radius: 12
        color: cardColor
        border.color: borderColor
        border.width: 1

        ColumnLayout {
            id: contentColumn
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            // 标题栏
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Text {
                    text: "今日值日生"
                    color: textPrimary
                    font.pixelSize: 15
                    font.bold: true
                }

                Item { Layout.fillWidth: true }

                Text {
                    id: dateLabel
                    color: textSecondary
                    font.pixelSize: 11
                }
            }

            // 组名 + 周次
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Rectangle {
                    Layout.preferredWidth: groupNameText.implicitWidth + 12
                    Layout.preferredHeight: 20
                    radius: 10
                    color: accentColor
                    Text {
                        id: groupNameText
                        anchors.centerIn: parent
                        text: "—"
                        color: "#ffffff"
                        font.pixelSize: 11
                        font.bold: true
                    }
                }

                Text {
                    id: weekLabel
                    color: textSecondary
                    font.pixelSize: 11
                }
            }

            // 成员列表
            Column {
                id: membersColumn
                Layout.fillWidth: true
                spacing: 6
            }

            Item { Layout.fillHeight: true }

            // 控制按钮
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Button {
                    text: "上一组"
                    Layout.preferredHeight: 26
                    font.pixelSize: 11
                    onClicked: backend.prev_group()
                }

                Button {
                    id: resetBtn
                    text: "重置"
                    Layout.preferredHeight: 26
                    font.pixelSize: 11
                    enabled: backend.get_manual_offset() !== 0
                    onClicked: backend.reset_group()
                }

                Button {
                    text: "下一组"
                    Layout.preferredHeight: 26
                    font.pixelSize: 11
                    onClicked: backend.next_group()
                }
            }
        }
    }

    // 刷新显示
    function refresh() {
        var data = backend.get_today_duty()
        if (!data) return

        groupNameText.text = data.groupName
        weekLabel.text = "第 " + data.weekNumber + " 周"
        dateLabel.text = data.date

        // 清空并重建成员列表
        membersColumn.children = []
        var members = data.members || []
        for (var i = 0; i < members.length; i++) {
            var m = members[i]
            var row = Qt.createQmlObject(
                'import QtQuick; Row { spacing: 8; }',
                membersColumn,
                "memberRow"
            )
            var nameTxt = Qt.createQmlObject(
                'import QtQuick; Text { color: "' + textPrimary + '"; font.pixelSize: 13; font.bold: true; }',
                row,
                "nameTxt"
            )
            nameTxt.text = m.name || "（未命名）"
            if (m.task) {
                var taskTxt = Qt.createQmlObject(
                    'import QtQuick; Text { color: "' + textSecondary + '"; font.pixelSize: 12; }',
                    row,
                    "taskTxt"
                )
                taskTxt.text = "· " + m.task
            }
        }

        if (members.length === 0) {
            var empty = Qt.createQmlObject(
                'import QtQuick; Text { color: "' + textSecondary + '"; font.pixelSize: 12; text: "暂无值日生"; }',
                membersColumn,
                "emptyTxt"
            )
        }
    }

    Connections {
        target: backend
        function onDutyChanged() { refresh() }
    }

    Component.onCompleted: refresh()
}
