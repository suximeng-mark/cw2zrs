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
    property var holidaysData: []
    property var todayData: null
    property var statsData: {"days": 0, "rows": [], "recent": []}

    function loadData() {
        if (!root.backend) return
        root.groupsData = JSON.parse(JSON.stringify(root.backend.get_groups()))
        root.startDateText = root.backend.get_start_date()
        root.rotationMode = root.backend.get_rotation_mode()
        root.holidaysData = JSON.parse(JSON.stringify(root.backend.get_holidays()))
        root.refreshTodayStats()
    }

    function refreshTodayStats() {
        if (!root.backend) return
        root.todayData = root.backend.get_today_duty()
        root.statsData = root.backend.get_stats()
    }

    function validDate(s) {
        return /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(new Date(s).getTime())
    }

    function addHoliday(start, end, name) {
        if (!root.validDate(start)) return false
        if (!end || !root.validDate(end)) end = start
        var arr = root.holidaysData.concat([{ start: start, end: end, name: name }])
        if (root.backend.save_holidays(JSON.stringify(arr))) {
            root.holidaysData = JSON.parse(JSON.stringify(root.backend.get_holidays()))
            root.refreshTodayStats()
            return true
        }
        return false
    }

    function removeHoliday(index) {
        var arr = root.holidaysData.filter(function(_, i) { return i !== index })
        if (root.backend.save_holidays(JSON.stringify(arr))) {
            root.holidaysData = JSON.parse(JSON.stringify(root.backend.get_holidays()))
            root.refreshTodayStats()
        }
    }

    function toggleMemberStatus(memberIndex) {
        if (!root.todayData) return
        var m = root.todayData.members[memberIndex]
        var next = (m && m.status === "absent") ? "normal" : "absent"
        if (root.backend.set_member_status(root.todayData.date, memberIndex, next))
            root.refreshTodayStats()
    }

    function formatRecordMembers(members) {
        var names = []
        for (var i = 0; i < members.length; i++) {
            var n = members[i].name || qsTr("未命名")
            if (members[i].status === "absent") n += qsTr("（假）")
            names.push(n)
        }
        return names.join("、")
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

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_calendar_cancel_20_regular"
        title: qsTr("假期安排")
        description: qsTr("假期内不轮换（寒暑假、法定节假日等），假期结束后自动衔接下一组；结束日期留空则按单日计算")

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                TextField {
                    id: holidayStartField
                    Layout.preferredWidth: 120
                    placeholderText: qsTr("开始 YYYY-MM-DD")
                }
                Text { text: "~"; opacity: 0.6 }
                TextField {
                    id: holidayEndField
                    Layout.preferredWidth: 120
                    placeholderText: qsTr("结束（可空）")
                }
                TextField {
                    id: holidayNameField
                    Layout.fillWidth: true
                    placeholderText: qsTr("假期名称（可选，如：国庆）")
                    onAccepted: root.addHolidayBtn.clicked()
                }
                Button {
                    id: addHolidayBtn
                    text: qsTr("添加假期")
                    highlighted: true
                    onClicked: {
                        var ok = root.addHoliday(
                            holidayStartField.text.trim(),
                            holidayEndField.text.trim(),
                            holidayNameField.text.trim()
                        )
                        if (ok) {
                            holidayStartField.text = ""
                            holidayEndField.text = ""
                            holidayNameField.text = ""
                        }
                    }
                }
            }

            Repeater {
                model: root.holidaysData

                delegate: RowLayout {
                    required property var modelData
                    required property int index

                    Layout.fillWidth: true
                    spacing: 8

                    Rectangle {
                        Layout.preferredHeight: 22
                        Layout.preferredWidth: holidayTagText.implicitWidth + 16
                        radius: 11
                        color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.1) : Qt.alpha("#000000", 0.06)

                        Text {
                            id: holidayTagText
                            anchors.centerIn: parent
                            text: qsTr("假期")
                            font.pixelSize: 11
                            color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                        }
                    }

                    Text {
                        text: modelData.start === modelData.end
                              ? modelData.start
                              : modelData.start + " ~ " + modelData.end
                        font.pixelSize: 13
                    }
                    Text {
                        text: modelData.name ? "· " + modelData.name : ""
                        font.pixelSize: 12
                        opacity: 0.6
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: qsTr("删除")
                        onClicked: root.removeHoliday(index)
                    }
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

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_person_prohibited_20_regular"
        title: qsTr("今日考勤")
        description: root.todayData
                     ? root.todayData.date + " · " + root.todayData.groupName
                       + (root.todayData.isHoliday ? " · " + (root.todayData.holidayName || qsTr("假期中")) : "")
                       + (root.todayData.switched ? " · " + qsTr("已手动调换") : "")
                     : qsTr("暂无数据")

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6

            Repeater {
                model: root.todayData ? root.todayData.members : []

                delegate: RowLayout {
                    required property var modelData
                    required property int index

                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: (modelData.name && modelData.name.length > 0)
                              ? modelData.name : qsTr("（未命名）")
                        font.pixelSize: 14
                        font.strikeout: modelData.status === "absent"
                        opacity: modelData.status === "absent" ? 0.5 : 1.0
                    }
                    Text {
                        text: modelData.task ? "· " + modelData.task : ""
                        font.pixelSize: 12
                        opacity: 0.55
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: modelData.status === "absent"
                              ? qsTr("恢复正常") : qsTr("标记请假")
                        highlighted: modelData.status !== "absent"
                        onClicked: root.toggleMemberStatus(index)
                    }
                }
            }

            Text {
                visible: !root.todayData || !root.todayData.members || root.todayData.members.length === 0
                text: qsTr("今日没有值日成员")
                opacity: 0.55
                font.pixelSize: 12
            }
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_data_histogram_20_regular"
        title: qsTr("值日统计")
        description: qsTr("自动记录每日值日，手动换组会标记为“调换”")

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: qsTr("已记录 %1 天值日").arg(root.statsData.days)
                    font.pixelSize: 13
                    opacity: 0.7
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: qsTr("清空记录")
                    enabled: root.statsData.days > 0
                    onClicked: clearHistoryPopup.open()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                visible: root.statsData.rows.length > 0

                Text { text: qsTr("姓名"); Layout.preferredWidth: 120; opacity: 0.5; font.pixelSize: 12 }
                Text { text: qsTr("值日次数"); Layout.preferredWidth: 80; opacity: 0.5; font.pixelSize: 12 }
                Text { text: qsTr("请假次数"); Layout.preferredWidth: 80; opacity: 0.5; font.pixelSize: 12 }
            }

            Repeater {
                model: root.statsData.rows

                delegate: RowLayout {
                    required property var modelData

                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: modelData.name
                        Layout.preferredWidth: 120
                        font.pixelSize: 13
                    }
                    Text {
                        text: modelData.count
                        Layout.preferredWidth: 80
                        font.pixelSize: 13
                    }
                    Text {
                        text: modelData.absent
                        Layout.preferredWidth: 80
                        font.pixelSize: 13
                        color: modelData.absent > 0 ? "#E5594F" : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
                    }
                }
            }

            Text {
                Layout.topMargin: 6
                text: qsTr("最近记录")
                font.pixelSize: 13
                font.bold: true
                visible: root.statsData.recent.length > 0
            }

            Repeater {
                model: root.statsData.recent

                delegate: ColumnLayout {
                    required property var modelData

                    Layout.fillWidth: true
                    spacing: 2

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            text: modelData.date
                            font.pixelSize: 12
                            opacity: 0.6
                            Layout.preferredWidth: 86
                        }
                        Text {
                            text: modelData.groupName
                            font.pixelSize: 12
                            font.bold: true
                        }
                        Text {
                            visible: modelData.switched
                            text: qsTr("调换")
                            font.pixelSize: 10
                            color: "#FFFFFF"
                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: -3
                                radius: 6
                                color: "#E5A100"
                                z: -1
                            }
                        }

                        Item { Layout.fillWidth: true }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.formatRecordMembers(modelData.members)
                        font.pixelSize: 12
                        opacity: 0.75
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    Popup {
        id: clearHistoryPopup
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        width: 320
        padding: 20
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        ColumnLayout {
            anchors.fill: parent
            spacing: 12

            Text {
                Layout.fillWidth: true
                text: qsTr("确定清空全部值日记录吗？")
                font.pixelSize: 15
                font.bold: true
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: qsTr("清空后无法恢复，不影响分组与轮换设置。")
                font.pixelSize: 12
                opacity: 0.6
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item { Layout.fillWidth: true }
                Button {
                    text: qsTr("取消")
                    onClicked: clearHistoryPopup.close()
                }
                Button {
                    text: qsTr("清空")
                    highlighted: true
                    onClicked: {
                        root.backend.clear_history()
                        root.refreshTodayStats()
                        clearHistoryPopup.close()
                    }
                }
            }
        }
    }

    Button {
        Layout.fillWidth: true
        text: qsTr("保存设置")
        highlighted: true
        onClicked: {
            root.doSave()
            root.refreshTodayStats()
        }
    }

    Connections {
        target: root.backend
        function onDutyChanged() { root.refreshTodayStats() }
    }
}
