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
        // backend 返回的是 QVariantList（只读），必须深拷贝为可变 JS 对象
        var raw = root.backend.get_groups()
        root.groupsData = JSON.parse(JSON.stringify(raw))
        root.startDateText = root.backend.get_start_date()
    }

    onBackendChanged: loadData()
    Component.onCompleted: Qt.callLater(loadData)

    // 添加成员：需要重新渲染列表，用不可变更新
    function addMember(groupIndex) {
        var arr = root.groupsData.slice()
        var g = arr[groupIndex]
        g.members = g.members.concat([{ name: "", task: "" }])
        root.groupsData = arr
    }

    // 删除成员
    function removeMember(groupIndex, memberIndex) {
        var arr = root.groupsData.slice()
        var g = arr[groupIndex]
        g.members = g.members.filter(function(_, i) { return i !== memberIndex })
        root.groupsData = arr
    }

    // 删除分组
    function removeGroup(groupIndex) {
        var arr = root.groupsData.slice()
        arr.splice(groupIndex, 1)
        root.groupsData = arr
    }

    // 添加分组
    function addGroup() {
        var arr = root.groupsData.slice()
        arr.push({
            name: qsTr("第%1组").arg(arr.length + 1),
            members: []
        })
        root.groupsData = arr
    }

    // 批量导入
    function importMembers(groupIndex, text) {
        var arr = root.groupsData.slice()
        var g = arr[groupIndex]
        if (!g) return 0
        var lines = text.split(/\r?\n/)
        var added = 0
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].replace(/^\s+|\s+$/g, "")
            if (line.length === 0) continue
            var parts
            if (/[，,]/.test(line)) {
                parts = line.split(/[，,]/)
            } else {
                parts = line.split(/[\s\u3000]+/)
            }
            var name = (parts[0] || "").replace(/^\s+|\s+$/g, "")
            var task = parts.length > 1 ? parts.slice(1).join(" ").replace(/^\s+|\s+$/g, "") : ""
            if (name.length === 0) continue
            g.members.push({ name: name, task: task })
            added++
        }
        if (added > 0) {
            root.groupsData = arr
        }
        return added
    }

    // 保存全部：统一调用后端，避免多次 save 出错
    function doSave() {
        if (!root.backend) {
            console.warn("[值日生] backend 为空，无法保存")
            return
        }
        try {
            var json = JSON.stringify(root.groupsData)
            root.backend.save_all(root.startDateText, json)
            console.log("[值日生] 保存指令已发送")
        } catch (e) {
            console.error("[值日生] 保存失败: " + e)
        }
    }

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
            id: groupDelegate
            required property var modelData
            required property int index

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
                        Layout.preferredWidth: 160
                        placeholderText: qsTr("组名")
                        text: group.name || ""
                        onEditingFinished: group.name = text
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: qsTr("删除该组")
                        onClicked: root.removeGroup(index)
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
                            onEditingFinished: modelData.name = text
                        }

                        TextField {
                            Layout.fillWidth: true
                            placeholderText: qsTr("任务，如：扫地")
                            text: modelData.task || ""
                            onEditingFinished: modelData.task = text
                        }

                        Button {
                            text: qsTr("删除")
                            onClicked: root.removeMember(groupDelegate.index, index)
                        }
                    }
                }

                // 添加成员 / 批量导入
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

                // 批量导入弹窗
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

    // ---------------- 添加分组 ----------------
    Button {
        Layout.fillWidth: true
        text: qsTr("+ 添加分组")
        onClicked: root.addGroup()
    }

    // ---------------- 保存 ----------------
    Button {
        Layout.fillWidth: true
        text: qsTr("保存设置")
        highlighted: true
        onClicked: root.doSave()
    }
}
