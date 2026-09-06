import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI

FluentPage {
    id: root

    title: qsTr("值日生设置")

    // 设置页导航跳转时会注入 pluginId
    property string pluginId: ""
    // 通过插件后端桥获取本插件后端
    property var backend: pluginId ? PluginBackendBridge.get_backend(pluginId) : null

    property var groupsData: []
    property string startDateText: ""

    function loadData() {
        if (!root.backend) return
        root.groupsData = root.backend.get_groups()
        root.startDateText = root.backend.get_start_date()
    }

    onBackendChanged: loadData()
    Component.onCompleted: Qt.callLater(loadData)

    // ---------------- 起始日期 ----------------
    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_calendar_start_20_regular"
        title: qsTr("轮换起始日期")
        description: qsTr("从该日期所在的一周开始计为第 1 周，值日小组按周自动轮换")

        RowLayout {
            spacing: 8

            TextField {
                id: startField
                text: root.startDateText
                placeholderText: "YYYY-MM-DD"
                onTextChanged: root.startDateText = text
            }

            Button {
                text: qsTr("设为今天")
                onClicked: {
                    var d = new Date()
                    var m = String(d.getMonth() + 1).padStart(2, "0")
                    var day = String(d.getDate()).padStart(2, "0")
                    startField.text = d.getFullYear() + "-" + m + "-" + day
                }
            }
        }
    }

    // ---------------- 分组列表 ----------------
    Repeater {
        model: root.groupsData

        delegate: Frame {
            required property var modelData
            required property int index

            // 供内层成员 Repeater 引用（内层 modelData 会遮蔽外层）
            property var group: modelData

            Layout.fillWidth: true
            topPadding: 14
            bottomPadding: 14
            leftPadding: 16
            rightPadding: 16

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                // 组名行
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: qsTr("第 %1 组").arg(index + 1)
                        typography: Typography.BodyStrong
                    }

                    TextField {
                        id: groupNameField
                        Layout.preferredWidth: 160
                        placeholderText: qsTr("组名")
                        text: modelData.name || ""
                        onTextChanged: modelData.name = text
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: qsTr("删除该组")
                        onClicked: {
                            root.groupsData.splice(index, 1)
                            root.groupsData = root.groupsData.slice()
                        }
                    }
                }

                // 成员列表
                Repeater {
                    model: group.members

                    delegate: RowLayout {
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        spacing: 8

                        TextField {
                            Layout.fillWidth: true
                            placeholderText: qsTr("姓名")
                            text: modelData.name || ""
                            onTextChanged: modelData.name = text
                        }

                        TextField {
                            Layout.fillWidth: true
                            placeholderText: qsTr("任务，如：扫地")
                            text: modelData.task || ""
                            onTextChanged: modelData.task = text
                        }

                        Button {
                            text: qsTr("删除")
                            onClicked: {
                                group.members.splice(index, 1)
                                root.groupsData = root.groupsData.slice()
                            }
                        }
                    }
                }

                // 添加成员
                Button {
                    text: qsTr("+ 添加成员")
                    onClicked: {
                        group.members.push({ name: "", task: "" })
                        root.groupsData = root.groupsData.slice()
                    }
                }
            }
        }
    }

    // ---------------- 添加分组 ----------------
    Button {
        Layout.fillWidth: true
        text: qsTr("+ 添加分组")
        onClicked: {
            root.groupsData.push({
                name: qsTr("第%1组").arg(root.groupsData.length + 1),
                members: []
            })
            root.groupsData = root.groupsData.slice()
        }
    }

    // ---------------- 保存 ----------------
    Button {
        Layout.fillWidth: true
        text: qsTr("保存设置")
        highlighted: true
        onClicked: {
            if (!root.backend) return
            root.backend.set_start_date(root.startDateText)
            root.backend.save_groups(root.groupsData)
        }
    }
}
