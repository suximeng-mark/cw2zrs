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

    height: miniMode ? 56 : (132 + memberCount * 28)
    implicitWidth: 250

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

    actions: Subtitle {
        text: root.duty ? root.duty.date : ""
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
                visible: !root.miniMode || index === 0

                Text {
                    text: (modelData.name && modelData.name.length > 0)
                          ? modelData.name : qsTr("（未命名）")
                    font.pixelSize: root.miniMode ? 13 : 15
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

        Item { Layout.fillHeight: true }

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
