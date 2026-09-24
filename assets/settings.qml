import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

PluginPage {
    id: root

    title: qsTr("值日生设置")
    pluginId: "com.studentondutyshow.com"

    // ===== 数据属性（与后端一一对应）=====
    property var groupsData: []
    property string startDateText: ""
    property string rotationMode: "weekly"
    property var holidaysData: []
    property var todayData: null
    property var statsData: {"days": 0, "rows": [], "recent": []}
    property var weekSchedule: {"monday": "", "sunday": "", "days": [], "groupNames": []}

    // 显示设置
    property int fontGroup: 12
    property int fontMeta: 12
    property int fontName: 14
    property int fontTask: 14
    property string memberLayout: "task"
    property string pairStyle: "paren"
    property bool showTomorrow: false
    property var pairStyleLabels: [
        qsTr("姓名（任务）"),
        qsTr("姓名·任务"),
        qsTr("两列对齐"),
        qsTr("任务：姓名")
    ]
    property var pairStyleValues: ["paren", "dot", "columns", "taskfirst"]

    // 值日提醒
    property bool reminderEnabled: false
    property string reminderTime: "07:30"
    property bool reminderSkipHoliday: true
    property bool reminderSupported: true

    // 导航：当前激活页索引
    property int currentPage: 0
    property var navItems: [
        { title: qsTr("界面设置"), icon: "ic_fluent_text_font_size_20_regular" },
        { title: qsTr("人员管理"), icon: "ic_fluent_people_20_regular" },
        { title: qsTr("轮换管理"), icon: "ic_fluent_arrow_sync_20_regular" },
        { title: qsTr("考勤与统计"), icon: "ic_fluent_data_histogram_20_regular" },
        { title: qsTr("迁移 / 备份"), icon: "ic_fluent_arrow_import_20_regular" }
    ]

    function pairStyleIndex() {
        var i = root.pairStyleValues.indexOf(root.pairStyle)
        return i >= 0 ? i : 0
    }

    function loadDisplayData() {
        if (!root.backend) return
        var d = root.backend.get_display_settings()
        if (!d) return
        root.fontGroup = d.fontGroup
        root.fontMeta = d.fontMeta
        root.fontName = d.fontName
        root.fontTask = d.fontTask
        root.memberLayout = d.memberLayout
        root.pairStyle = d.pairStyle
        root.showTomorrow = !!d.showTomorrow
        // pairCombo 位于页面内，其 Component.onCompleted 自行读取 pairStyle
    }

    function pushDisplaySettings() {
        if (!root.backend) return
        root.backend.save_display_settings(
            root.fontGroup, root.fontMeta, root.fontName, root.fontTask,
            root.memberLayout, root.pairStyle, root.showTomorrow
        )
    }

    function loadReminderData() {
        if (!root.backend) return
        var d = root.backend.get_reminder_settings()
        if (!d) return
        root.reminderEnabled = !!d.enabled
        root.reminderTime = d.time || "07:30"
        root.reminderSkipHoliday = d.skipHoliday !== false
        root.reminderSupported = d.supported !== false
    }

    function pushReminderSettings() {
        if (!root.backend) return
        var ok = root.backend.save_reminder_settings(
            root.reminderEnabled, root.reminderTime, root.reminderSkipHoliday
        )
        if (ok) {
            reminderResultText.text = qsTr("已保存")
            reminderResultText.color = "#2E7D32"
        } else {
            var d = root.backend.get_reminder_settings()
            if (d) {
                root.reminderEnabled = !!d.enabled
                root.reminderTime = d.time || "07:30"
                root.reminderSkipHoliday = d.skipHoliday !== false
            }
            reminderResultText.text = qsTr("保存失败：时间格式需为 HH:MM（24 小时制），如 07:30")
            reminderResultText.color = "#E5594F"
        }
    }

    function testReminder() {
        if (!root.backend) return
        var r = root.backend.test_reminder()
        reminderResultText.text = r.msg
        reminderResultText.color = r.ok ? "#2E7D32" : "#E5594F"
    }

    function loadData() {
        if (!root.backend) return
        root.groupsData = root.clone(root.backend.get_groups())
        root.startDateText = root.backend.get_start_date()
        root.rotationMode = root.backend.get_rotation_mode()
        root.holidaysData = root.clone(root.backend.get_holidays())
        root.loadDisplayData()
        root.loadReminderData()
        root.refreshTodayStats()
    }

    function refreshTodayStats() {
        if (!root.backend) return
        root.todayData = root.backend.get_today_duty()
        root.statsData = root.backend.get_stats()
        root.weekSchedule = root.backend.get_week_schedule()
    }

    function clone(o) {
        return JSON.parse(JSON.stringify(o))
    }

    function applyTempSwap(day, groupIndex) {
        if (!root.backend) return false
        var ok = root.backend.set_temp_swap(day, groupIndex)
        if (ok) root.refreshTodayStats()
        return ok
    }

    function reloadHolidays() {
        root.holidaysData = root.clone(root.backend.get_holidays())
        root.refreshTodayStats()
    }

    function validDate(s) {
        return /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(new Date(s).getTime())
    }

    function addHoliday(start, end, name) {
        if (!root.validDate(start)) return false
        if (!end || !root.validDate(end)) end = start
        var arr = root.holidaysData.concat([{ start: start, end: end, name: name }])
        if (root.backend.save_holidays(JSON.stringify(arr))) {
            root.reloadHolidays()
            return true
        }
        return false
    }

    function removeHoliday(index) {
        var arr = root.holidaysData.filter(function(_, i) { return i !== index })
        if (root.backend.save_holidays(JSON.stringify(arr)))
            root.reloadHolidays()
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

    function groupAt(gi) { return root.groupsData[gi] || null }
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
            var parts = /[，,]/.test(line) ? line.split(/[，,]/) : line.split(/[\s　]+/)
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

    // ===== 主布局：左侧导航 + 右侧可滚动内容 =====
    RowLayout {
        Layout.fillWidth: true
        spacing: 0

        // ---------- 左侧导航栏 ----------
        Rectangle {
            id: sidebar
            Layout.preferredWidth: 150
            Layout.fillHeight: true
            color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.04) : Qt.alpha("#000000", 0.03)

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 4

                Repeater {
                    model: root.navItems

                    delegate: Rectangle {
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        radius: 8
                        color: root.currentPage === index
                               ? (Theme.isDark() ? Qt.alpha("#FFFFFF", 0.12) : Qt.alpha("#000000", 0.08))
                               : "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10

                            Icon {
                                name: modelData.icon
                                width: 18
                                height: 18
                                color: root.currentPage === index
                                       ? Colors.proxy.primaryColor
                                       : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
                            }

                            Text {
                                Layout.fillWidth: true
                                text: modelData.title
                                font.pixelSize: 13
                                font.weight: root.currentPage === index ? Font.DemiBold : Font.Normal
                                color: root.currentPage === index
                                       ? Colors.proxy.primaryColor
                                       : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
                                elide: Text.ElideRight
                            }
                        }

                        TapHandler {
                            onTapped: root.currentPage = index
                        }
                    }
                }

                Item { Layout.fillHeight: true }
            }
        }

        // 分隔线
        Rectangle {
            Layout.preferredWidth: 1
            Layout.fillHeight: true
            color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.1) : Qt.alpha("#000000", 0.08)
        }

        // ---------- 右侧内容区 ----------
        ColumnLayout {
            id: contentColumn
            Layout.fillWidth: true
            Layout.leftMargin: 12
            spacing: 12

                // =====================================================
                // 页面 0：界面设置
                // =====================================================

        ColumnLayout {
            visible: root.currentPage === 0
            spacing: 12
            Layout.fillWidth: true

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_text_font_size_20_regular"
                title: qsTr("字号设置")
                description: qsTr("四个区域字号独立调节（9~28px），拖动即时预览")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    FontSliderRow {
                        labelText: qsTr("组名")
                        sliderValue: root.fontGroup
                        onSliderMoved: { root.fontGroup = value; root.pushDisplaySettings() }
                    }
                    FontSliderRow {
                        labelText: qsTr("周期/徽标")
                        sliderValue: root.fontMeta
                        onSliderMoved: { root.fontMeta = value; root.pushDisplaySettings() }
                    }
                    FontSliderRow {
                        labelText: qsTr("成员姓名")
                        sliderValue: root.fontName
                        onSliderMoved: { root.fontName = value; root.pushDisplaySettings() }
                    }
                    FontSliderRow {
                        labelText: qsTr("任务")
                        sliderValue: root.fontTask
                        onSliderMoved: { root.fontTask = value; root.pushDisplaySettings() }
                    }
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_people_20_regular"
                title: qsTr("排列与配对")
                description: qsTr("成员排列控制普通模式密度；姓名对应控制姓名与任务的配对样式（紧凑/普通均生效）")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        Label { text: qsTr("成员排列"); opacity: 0.7; font.pixelSize: 12; Layout.preferredWidth: 72 }
                        RadioButton {
                            text: qsTr("合并一行")
                            checked: root.memberLayout === "inline"
                            onClicked: { root.memberLayout = "inline"; root.pushDisplaySettings() }
                        }
                        RadioButton {
                            text: qsTr("按岗位分行")
                            checked: root.memberLayout === "task"
                            onClicked: { root.memberLayout = "task"; root.pushDisplaySettings() }
                        }
                        RadioButton {
                            text: qsTr("每人一行")
                            checked: root.memberLayout === "person"
                            onClicked: { root.memberLayout = "person"; root.pushDisplaySettings() }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        Label { text: qsTr("姓名对应"); opacity: 0.7; font.pixelSize: 12; Layout.preferredWidth: 72 }
                        ComboBox {
                            id: pairCombo
                            Layout.fillWidth: true
                            model: root.pairStyleLabels
                            Component.onCompleted: currentIndex = root.pairStyleIndex()
                            onActivated: {
                                root.pairStyle = root.pairStyleValues[index]
                                root.pushDisplaySettings()
                            }
                        }
                    }

                    Switch {
                        text: qsTr("在部件中显示明日值日预告（紧凑 / 普通模式均生效）")
                        checked: root.showTomorrow
                        enabled: !!root.backend
                        onToggled: { root.showTomorrow = checked; root.pushDisplaySettings() }
                    }
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_alert_20_regular"
                title: qsTr("值日提醒")
                description: qsTr("每天指定时间弹出系统通知，提醒今日值日生；需保持 Class Widgets 2 处于运行状态")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Switch {
                        text: qsTr("启用每日提醒")
                        checked: root.reminderEnabled
                        enabled: root.reminderSupported
                        onToggled: { root.reminderEnabled = checked; root.pushReminderSettings() }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        enabled: root.reminderSupported

                        Label { text: qsTr("提醒时间"); opacity: 0.7; font.pixelSize: 12 }
                        TextField {
                            id: reminderTimeField
                            Layout.preferredWidth: 92
                            text: root.reminderTime
                            placeholderText: "07:30"
                            horizontalAlignment: Text.AlignHCenter
                            onEditingFinished: {
                                root.reminderTime = text.trim()
                                root.pushReminderSettings()
                            }
                        }
                        CheckBox {
                            text: qsTr("假期不提醒")
                            checked: root.reminderSkipHoliday
                            onToggled: { root.reminderSkipHoliday = checked; root.pushReminderSettings() }
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: qsTr("立即测试提醒")
                            onClicked: root.testReminder()
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: !root.reminderSupported
                        text: qsTr("当前 Class Widgets 版本不支持系统通知，更新到新版后即可使用值日提醒")
                        color: "#E5594F"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    ResultText { id: reminderResultText }
                }
            }
        }

                // =====================================================
                // 页面 1：人员管理
                // =====================================================

        ColumnLayout {
            visible: root.currentPage === 1
            spacing: 12
            Layout.fillWidth: true

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_people_20_regular"
                title: qsTr("分组与成员")
                description: qsTr("点击组名可编辑；每行一个成员，姓名与任务分别填写")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 12

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
                }
            }

            Button {
                Layout.fillWidth: true
                text: qsTr("保存人员设置")
                highlighted: true
                onClicked: {
                    root.doSave()
                    root.refreshTodayStats()
                }
            }
        }

                // =====================================================
                // 页面 2：轮换管理
                // =====================================================

        ColumnLayout {
            visible: root.currentPage === 2
            spacing: 12
            Layout.fillWidth: true

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
                description: qsTr("假期内不自动轮换；结束日期留空则按单日计算")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        TextField {
                            id: holidayStartField
                            Layout.preferredWidth: 120
                            Layout.minimumWidth: 80
                            placeholderText: qsTr("开始日期")
                        }
                        Text { text: "~"; opacity: 0.6 }
                        TextField {
                            id: holidayEndField
                            Layout.preferredWidth: 120
                            Layout.minimumWidth: 80
                            placeholderText: qsTr("结束可空")
                        }
                        TextField {
                            id: holidayNameField
                            Layout.fillWidth: true
                            Layout.minimumWidth: 90
                            placeholderText: qsTr("假期名称（可选）")
                            onAccepted: addHolidayBtn.clicked()
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

            Frame {
                Layout.fillWidth: true
                leftPadding: 18
                rightPadding: 18
                topPadding: 16
                bottomPadding: 16

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 18

                        Icon {
                            name: "ic_fluent_calendar_start_20_regular"
                            size: 22
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            Text {
                                Layout.fillWidth: true
                                text: qsTr("本周值日预览")
                                font.pixelSize: 14
                                color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.weekSchedule && root.weekSchedule.monday
                                      ? root.weekSchedule.monday + " ~ " + root.weekSchedule.sunday
                                      : qsTr("周一至周日排班一览；临时调班的日期会高亮标记")
                                font.pixelSize: 12
                                color: Theme.currentTheme.colors.textSecondaryColor
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 7
                        rowSpacing: 6
                        columnSpacing: 6

                        Repeater {
                            model: root.weekSchedule ? root.weekSchedule.days : []

                            delegate: Rectangle {
                                required property var modelData

                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Layout.preferredHeight: 96
                                radius: 8
                                color: modelData.isToday
                                       ? (Theme.isDark() ? Qt.alpha(Colors.proxy.primaryColor, 0.25) : Qt.alpha(Colors.proxy.primaryColor, 0.12))
                                       : modelData.isHoliday
                                         ? (Theme.isDark() ? Qt.alpha("#FFFFFF", 0.04) : "#FFF5DC")
                                         : (Theme.isDark() ? Qt.alpha("#FFFFFF", 0.06) : Qt.alpha("#000000", 0.03))
                                border.width: modelData.isSwap ? 1 : 0
                                border.color: "#E5A100"

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    spacing: 2

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 4

                                        Text {
                                            text: modelData.weekday
                                            font.pixelSize: 11
                                            font.bold: true
                                            color: modelData.isToday ? Colors.proxy.primaryColor : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
                                        }
                                        Text {
                                            text: modelData.date.slice(5)
                                            font.pixelSize: 10
                                            opacity: 0.6
                                        }
                                        Item { Layout.fillWidth: true }
                                        Rectangle {
                                            visible: modelData.isSwap
                                            implicitWidth: 18
                                            implicitHeight: 16
                                            Layout.preferredWidth: 18
                                            Layout.preferredHeight: 16
                                            radius: 8
                                            color: "#E5A100"

                                            Text {
                                                anchors.centerIn: parent
                                                text: qsTr("调")
                                                font.pixelSize: 10
                                                font.bold: true
                                                color: "#FFFFFF"
                                            }
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.isHoliday
                                              ? (modelData.holidayName || qsTr("假期"))
                                              : modelData.groupName
                                        font.pixelSize: 12
                                        font.bold: !modelData.isHoliday
                                        color: modelData.isHoliday ? "#B8860B" : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
                                        elide: Text.ElideRight
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        text: {
                                            if (modelData.isHoliday) return ""
                                            var names = []
                                            for (var i = 0; i < modelData.members.length; i++)
                                                names.push(modelData.members[i].name)
                                            return names.join("、")
                                        }
                                        font.pixelSize: 10
                                        opacity: 0.7
                                        wrapMode: Text.WordWrap
                                        elide: Text.ElideRight
                                        maximumLineCount: 2
                                    }

                                    Text {
                                        visible: modelData.isSwap && modelData.autoGroupName
                                        Layout.fillWidth: true
                                        text: qsTr("原:") + modelData.autoGroupName
                                        font.pixelSize: 9
                                        color: "#E5A100"
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }
            }


            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_arrow_sync_20_regular"
                title: qsTr("临时调班")
                description: qsTr("指定某天由哪个小组值日，仅覆盖当日，不影响轮换计数")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Label { text: qsTr("日期"); opacity: 0.7; font.pixelSize: 12 }
                        TextField {
                            id: swapDateField
                            Layout.preferredWidth: 130
                            Layout.minimumWidth: 90
                            Layout.fillWidth: true
                            placeholderText: "YYYY-MM-DD"
                            text: new Date().toISOString().slice(0, 10)
                        }

                        Label { text: qsTr("值日组"); opacity: 0.7; font.pixelSize: 12 }
                        ComboBox {
                            id: swapGroupCombo
                            Layout.preferredWidth: 150
                            Layout.minimumWidth: 90
                            Layout.fillWidth: true
                            model: root.weekSchedule ? root.weekSchedule.groupNames : []
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Button {
                            text: qsTr("应用调班")
                            highlighted: true
                            onClicked: {
                                var ok = root.applyTempSwap(swapDateField.text.trim(), swapGroupCombo.currentIndex)
                                swapResultText.text = ok ? qsTr("已设置调班") : qsTr("设置失败：日期格式应为 YYYY-MM-DD")
                                swapResultText.color = ok ? "#2E7D32" : "#E5594F"
                            }
                        }

                        Button {
                            text: qsTr("清除该日调班")
                            onClicked: {
                                var ok = root.applyTempSwap(swapDateField.text.trim(), -1)
                                swapResultText.text = ok ? qsTr("已清除调班") : qsTr("清除失败")
                                swapResultText.color = ok ? "#2E7D32" : "#E5594F"
                            }
                        }

                        Item { Layout.fillWidth: true }
                    }

                    ResultText { id: swapResultText }
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_table_20_regular"
                title: qsTr("值日表导出")
                description: qsTr("按当前轮换规则生成未来排班，逐日一行（含周末与假期标记），同时导出 CSV 和 HTML 到桌面")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        WeekButton {
                            weeks: 2
                            backend: root.backend
                            onDone: { scheduleResultText.text = result.msg; scheduleResultText.color = result.ok ? "#2E7D32" : "#E5594F" }
                        }
                        WeekButton {
                            weeks: 4
                            accent: true
                            backend: root.backend
                            onDone: { scheduleResultText.text = result.msg; scheduleResultText.color = result.ok ? "#2E7D32" : "#E5594F" }
                        }
                        WeekButton {
                            weeks: 8
                            backend: root.backend
                            onDone: { scheduleResultText.text = result.msg; scheduleResultText.color = result.ok ? "#2E7D32" : "#E5594F" }
                        }

                        Item { Layout.fillWidth: true }
                    }

                    ResultText { id: scheduleResultText }
                }
            }

            Button {
                Layout.fillWidth: true
                text: qsTr("保存轮换设置")
                highlighted: true
                onClicked: {
                    root.doSave()
                    root.refreshTodayStats()
                }
            }
        }

                // =====================================================
                // 页面 3：考勤与统计
                // =====================================================

        ColumnLayout {
            visible: root.currentPage === 3
            spacing: 12
            Layout.fillWidth: true

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
                icon.name: "ic_fluent_arrow_sync_20_regular"
                title: qsTr("手动换组")
                description: qsTr("临时切换今日值日小组，不影响自动轮换规则；点击重置恢复自动计算结果")

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Button {
                        text: qsTr("上一组")
                        onClicked: { if (root.backend) root.backend.prev_group() }
                    }
                    Button {
                        text: qsTr("重置")
                        enabled: root.todayData ? root.todayData.offset !== 0 : false
                        onClicked: { if (root.backend) root.backend.reset_group() }
                    }
                    Button {
                        text: qsTr("下一组")
                        highlighted: true
                        onClicked: { if (root.backend) root.backend.next_group() }
                    }

                    Item { Layout.fillWidth: true }
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

                            Text { text: modelData.name; Layout.preferredWidth: 120; font.pixelSize: 13 }
                            Text { text: modelData.count; Layout.preferredWidth: 80; font.pixelSize: 13 }
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
        }

                // =====================================================
                // 页面 4：迁移 / 备份
                // =====================================================

        ColumnLayout {
            visible: root.currentPage === 4
            spacing: 12
            Layout.fillWidth: true

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_arrow_import_20_regular"
                title: qsTr("配置导入 / 导出")
                description: qsTr("导出当前分组、轮换和假期到文件；从文件快速导入配置（不含历史记录和手动调换）")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    TextField {
                        id: configPathField
                        Layout.fillWidth: true
                        text: Qt.platform.os === "windows" ? "C:/Users/Lenovo/Desktop/duty_config.json" : "~/Desktop/duty_config.json"
                        placeholderText: qsTr("文件路径，如 C:/Users/.../duty_config.json")
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Button {
                            text: qsTr("导出配置")
                            onClicked: {
                                var r = root.backend.export_config(configPathField.text)
                                configResultText.text = r.ok ? qsTr("已导出到：") + r.msg : qsTr("导出失败：") + r.msg
                                configResultText.color = r.ok ? "#2E7D32" : "#E5594F"
                            }
                        }

                        Button {
                            text: qsTr("导入配置")
                            highlighted: true
                            onClicked: {
                                var r = root.backend.import_config(configPathField.text)
                                configResultText.text = r.ok ? r.msg : qsTr("导入失败：") + r.msg
                                configResultText.color = r.ok ? "#2E7D32" : "#E5594F"
                                if (r.ok) root.loadData()
                            }
                        }

                        Item { Layout.fillWidth: true }
                    }

                    ResultText { id: configResultText }
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_table_20_regular"
                title: qsTr("值日表导出")
                description: qsTr("按当前轮换规则生成未来排班，导出 CSV（Excel 可编辑）和 HTML（可打印/存 PDF）到桌面")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        WeekButton {
                            weeks: 2
                            backend: root.backend
                            onDone: { backupScheduleText.text = result.msg; backupScheduleText.color = result.ok ? "#2E7D32" : "#E5594F" }
                        }
                        WeekButton {
                            weeks: 4
                            accent: true
                            backend: root.backend
                            onDone: { backupScheduleText.text = result.msg; backupScheduleText.color = result.ok ? "#2E7D32" : "#E5594F" }
                        }
                        WeekButton {
                            weeks: 8
                            backend: root.backend
                            onDone: { backupScheduleText.text = result.msg; backupScheduleText.color = result.ok ? "#2E7D32" : "#E5594F" }
                        }

                        Item { Layout.fillWidth: true }
                    }

                    ResultText { id: backupScheduleText }
                }
            }
        }
        }
    }

    // ============================================================
    // 公共组件
    // ============================================================
    component FontSliderRow: RowLayout {
        id: fontRow
        property string labelText: ""
        property int sliderValue: 12
        signal sliderMoved(int value)

        Layout.fillWidth: true
        spacing: 10

        Text {
            text: fontRow.labelText
            opacity: 0.7
            font.pixelSize: 12
            Layout.preferredWidth: 72
        }
        Slider {
            Layout.fillWidth: true
            from: 9
            to: 28
            stepSize: 1
            value: fontRow.sliderValue
            onMoved: fontRow.sliderMoved(Math.round(value))
        }
        Text {
            text: fontRow.sliderValue + " px"
            font.pixelSize: 12
            Layout.preferredWidth: 44
            horizontalAlignment: Text.AlignRight
        }
    }

    // “未来 N 周”导出按钮
    component WeekButton: Button {
        id: weekBtn
        property int weeks: 1
        property bool accent: false
        property var backend: null
        signal done(var result)

        highlighted: weekBtn.accent
        text: qsTr("未来 %1 周").arg(weekBtn.weeks)
        onClicked: {
            if (weekBtn.backend)
                weekBtn.done(weekBtn.backend.export_schedule(weekBtn.weeks))
        }
    }

    // 通用保存结果文本
    component ResultText: Text {
        Layout.fillWidth: true
        font.pixelSize: 12
        wrapMode: Text.WordWrap
        visible: text.length > 0
    }

    // ============================================================
    // 页面 0：界面设置
    // ============================================================

    // ============================================================
    // 页面 1：人员管理
    // ============================================================

    // ============================================================
    // 页面 2：轮换管理
    // ============================================================

    // ============================================================
    // 页面 3：考勤与统计
    // ============================================================

    // ============================================================
    // 页面 4：迁移 / 备份
    // ============================================================

    // 清空历史确认弹窗（全局唯一）
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

    Connections {
        target: root.backend ? root.backend : null
        function onDutyChanged() { root.refreshTodayStats() }
    }
}
