import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Theme

Widget {
    id: root

    property var duty: null
    property int memberCount: 0

    text: qsTr("今日值日生")

    height: miniMode ? 40 : (132 + memberCount * 28)
    implicitWidth: miniMode ? 220 : 250

    onBackendChanged: refresh()
    Component.onCompleted: Qt.callLater(refresh)

    Connections {
        target: root.backend
        function onDutyChanged() { refresh() }
    }

    function refresh() {
        if (!root.backend) return
        root.duty = root.backend.get_today_duty()
        root.memberCount = (root.duty && root.duty.members) ? root.duty.members.length : 0
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
        var max = Math.min(root.duty.members.length, 3)
        for (var i = 0; i < max; i++) {
            var n = root.duty.members[i].name
            names.push((n && n.length > 0) ? n : qsTr("未命名"))
        }
        var s = names.join("、")
        if (root.duty.members.length > 3) s += "…"
        return s
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

        // ===== 紧凑模式：单行显示 =====
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 6
            visible: root.miniMode

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
                Layout.fillWidth: true
                text: root.membersInlineText()
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
            }

            Text {
                text: root.periodText()
                font.pixelSize: 10
                opacity: 0.55
                visible: root.duty
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

            Item { Layout.fillWidth: true }
        }

        Repeater {
            model: root.duty ? root.duty.members : []

            delegate: RowLayout {
                Layout.fillWidth: true
                spacing: 8
                visible: !root.miniMode

                Text {
                    text: (modelData.name && modelData.name.length > 0)
                          ? modelData.name : qsTr("（未命名）")
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                }

                Text {
                    text: modelData.task ? "· " + modelData.task : ""
                    font.pixelSize: 13
                    color: Theme.isDark()
                           ? Qt.alpha("#FFFFFF", 0.6)
                           : Qt.alpha("#000000", 0.55)
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
