import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

PluginPage {
    id: root

    title: qsTr("值日生设置")
    pluginId: "com.studentondutyshow.com"

    property var groupsData: []
    property string startDateText: ""
    property string rotationMode: "weekly"

    function loadData() {
        if (!root.backend) return
        root.groupsData = JSON.parse(JSON.stringify(root.backend.get_groups()))
        root.startDateText = root.backend.get_start_date()
        root.rotationMode = root.backend.get_rotation_mode()
    }

    onBackendChanged: loadData()
    Component.onCompleted: Qt.callLater(loadData)

    function groupAt(gi) {
        return root.groupsData[gi] || null
    }
    function memberAt(gi, mi) {
        var g = root.groupsData[gi]
        return (g && g.members && g.members[mi]) ? g.members[mi] : null
    }

    function addMember(groupIndex) {
        var arr = root.groupsData.slice()
        arr[groupIndex].members = arr[groupIndex].members.concat([{ name: "", task: "" }])
        root.groupsData = arr
    }

    function removeMember(groupIndex, memberIndex) {
        var arr = root.groupsData.slice()
        arr[groupIndex].members = arr[groupIndex].members.filter(function(_, i) { return i !== memberIndex })
        root.groupsData = arr
    }

    function removeGroup(groupIndex) {
        var arr = root.groupsData.slice()
        arr.splice(groupIndex, 1)
        root.groupsData = arr
    }

    function addGroup() {
        var arr = root.groupsData.slice()
        arr.push({ name: qsTr("第%1组").arg(arr.length + 1), members: [] })
        root.groupsData = arr
    }

    function importMembers(groupIndex, text) {
        var g = root.groupsData[groupIndex]
        if (!g) return 0
        var added = 0
        var lines = text.split(/\r?\n/)
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim()
            if (!line) continue
            var parts = /[，,]/.test(line) ? line.split(/[，,]/) : line.split(/[\s\u3000]+/)
            var name = (parts[0] || "").trim()
            if (!name) continue
            var task = parts.length > 1 ? parts.slice(1).join(" ").trim() : ""
            g.members.push({ name: name, task: task })
            added++
        }
        if (added > 0) root.groupsData = root.groupsData.slice()
        return added
    }

    function doSave() {
        if (!root.backend) return
        try {
            root.backend.save_all(
                root.startDateText,
                root.rotationMode,
                JSON.stringify(root.groupsData)
            )
        } catch (e) {
            console.error("[值日生] 保存失败: " + e)
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_arrow_sync_20_regular"
        title: qsTr("轮换方式")
        description: qsTr("按周：每周换一组；每天：每日换一组；工作日：周一至周五每天换，周末（六日）仅算 1 日")

        RowLayout {
            spacing: 12

            RadioButton {
                text: qsTr("按周轮换")
                checked: root.rotationMode === "weekly"
                onClicked: root.rotationMode = "weekly"
            }
            RadioButton {
                text: qsTr("每天轮换")
                checked: root.rotationMode === "daily"
                onClicked: root.rotationMode = "daily"
            }
            RadioButton {
                text: qsTr("工作日轮换")
                checked: root.rotationMode === "workday"
                onClicked: root.rotationMode = "workday"
            }
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_calendar_start_20_regular"
        title: qsTr("轮换起始日期")
        description: root.rotationMode === "daily"
                     ? qsTr("从该日期开始计为第 1 天，值日小组每天自动轮换")
                     : root.rotationMode === "workday"
                       ? qsTr("从该日期开始，周一至周五每天轮换，周末仅算 1 日")
                       : qsTr("从该日期所在的一周开始计为第 1 周，值日小组按周自动轮换")

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

    Repeater {
        model: root.groupsData

        delegate: Frame {
            id: groupDelegate
            required property var modelData
            required property int index

            Layout.fillWidth: true
            topPadding: 14
            bottomPadding: 14
            leftPadding: 16
            rightPadding: 16

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: qsTr("第 %1 组").arg(groupDelegate.index + 1)
                        typography: Typography.BodyStrong
                    }

                    TextField {
                        Layout.preferredWidth: 160
                        placeholderText: qsTr("组名")
                        text: root.groupAt(groupDelegate.index) ? root.groupAt(groupDelegate.index).name : ""
                        onTextChanged: {
                            var g = root.groupAt(groupDelegate.index)
                            if (g) g.name = text
                        }
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: qsTr("删除该组")
                        onClicked: root.removeGroup(groupDelegate.index)
                    }
                }

                Repeater {
                    model: groupDelegate.modelData.members

                    delegate: RowLayout {
                        required property int index

                        Layout.fillWidth: true
                        spacing: 8

                        TextField {
                            Layout.fillWidth: true
                            placeholderText: qsTr("姓名")
                            text: {
                                var m = root.memberAt(groupDelegate.index, index)
                                return m ? m.name : ""
                            }
                            onTextChanged: {
                                var m = root.memberAt(groupDelegate.index, index)
                                if (m) m.name = text
                            }
                        }

                        TextField {
                            Layout.fillWidth: true
                            placeholderText: qsTr("任务，如：扫地")
                            text: {
                                var m = root.memberAt(groupDelegate.index, index)
                                return m ? m.task : ""
                            }
                            onTextChanged: {
                                var m = root.memberAt(groupDelegate.index, index)
                                if (m) m.task = text
                            }
                        }

                        Button {
                            text: qsTr("删除")
                            onClicked: root.removeMember(groupDelegate.index, index)
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Button {
                        text: qsTr("+ 添加成员")
                        onClicked: root.addMember(groupDelegate.index)
                    }

                    Button {
                        text: qsTr("批量导入")
                        onClicked: importPopup.open()
                    }

                    Item { Layout.fillWidth: true }
                }

                Popup {
                    id: importPopup
                    parent: Overlay.overlay
                    anchors.centerIn: parent
                    modal: true
                    focus: true
                    width: 420
                    padding: 20
                    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10

                        Text {
                            Layout.fillWidth: true
                            text: qsTr("批量导入成员")
                            font.bold: true
                            font.pixelSize: 16
                        }

                        Text {
                            Layout.fillWidth: true
                            text: qsTr("每行一个成员。格式：\n  姓名 任务\n  姓名,任务\n  姓名（仅姓名）")
                            color: "#888"
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }

                        TextArea {
                            id: importArea
                            Layout.fillWidth: true
                            Layout.preferredHeight: 160
                            placeholderText: qsTr("张三 扫地\n李四,擦黑板\n王五")
                            wrapMode: TextArea.Wrap
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Item { Layout.fillWidth: true }

                            Button {
                                text: qsTr("取消")
                                onClicked: importPopup.close()
                            }

                            Button {
                                text: qsTr("导入")
                                highlighted: true
                                onClicked: {
                                    root.importMembers(groupDelegate.index, importArea.text)
                                    importArea.text = ""
                                    importPopup.close()
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Button {
        Layout.fillWidth: true
        text: qsTr("+ 添加分组")
        onClicked: root.addGroup()
    }

    Button {
        Layout.fillWidth: true
        text: qsTr("保存设置")
        highlighted: true
        onClicked: root.doSave()
    }
}
