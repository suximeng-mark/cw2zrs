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
    property string weekendMode: "merge"
    property var holidaysData: []
    property var todayData: null
    property var statsData: {"days": 0, "rows": [], "recent": []}
    property var weekSchedule: {"monday": "", "sunday": "", "days": [], "groupNames": []}
    property var monthInfo: {"year": 0, "month": 0, "days": []}

    // 显示设置（含组件显隐）
    property int fontGroup: 12
    property int fontMeta: 12
    property int fontName: 14
    property int fontTask: 14
    property bool showGroup: true
    property bool showName: true
    property bool showTask: true
    property bool showMeta: true
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

    // 备份内容勾选
    property bool backupDisplay: true
    property bool backupPeople: true
    property bool backupRotation: true
    property bool backupHistory: true

    // 月历状态
    property int calYear: 0
    property int calMonth: 0
    property string selectedDate: ""

    // 编辑版本号：切换组/增删成员后强制刷新绑定
    property int editRev: 0

    // 导航：当前激活页索引
    property int currentPage: 0
    property var navItems: [
        { title: qsTr("界面设置"), icon: "ic_fluent_text_font_size_20_regular" },
        { title: qsTr("人员设置"), icon: "ic_fluent_people_20_regular" },
        { title: qsTr("轮换管理"), icon: "ic_fluent_arrow_sync_20_regular" },
        { title: qsTr("请假管理"), icon: "ic_fluent_person_prohibited_20_regular" },
        { title: qsTr("实验性功能"), icon: "ic_fluent_alert_20_regular" },
        { title: qsTr("备份 / 迁移"), icon: "ic_fluent_arrow_import_20_regular" }
    ]

    function pairStyleIndex() {
        var i = root.pairStyleValues.indexOf(root.pairStyle)
        return i >= 0 ? i : 0
    }

    function saveStamp() {
        var d = new Date()
        function p(n) { return String(n).padStart(2, "0") }
        return d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate())
               + " " + p(d.getHours()) + ":" + p(d.getMinutes())
    }

    function clone(o) {
        return JSON.parse(JSON.stringify(o))
    }

    // ===== 显示设置 =====
    function loadDisplayData() {
        if (!root.backend) return
        var d = root.backend.get_display_settings()
        if (!d) return
        root.fontGroup = d.fontGroup
        root.fontMeta = d.fontMeta
        root.fontName = d.fontName
        root.fontTask = d.fontTask
        root.showGroup = d.showGroup !== false
        root.showName = d.showName !== false
        root.showTask = d.showTask !== false
        root.showMeta = d.showMeta !== false
        root.memberLayout = d.memberLayout
        root.pairStyle = d.pairStyle
        root.showTomorrow = !!d.showTomorrow
    }

    function pushDisplaySettings() {
        if (!root.backend) return
        root.backend.save_display_settings(
            root.showGroup, root.showName, root.showTask, root.showMeta,
            root.fontGroup, root.fontMeta, root.fontName, root.fontTask,
            root.memberLayout, root.pairStyle, root.showTomorrow
        )
    }

    // ===== 值日提醒 =====
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
            reminderResultText.text = qsTr("保存成功 ") + root.saveStamp()
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

    // ===== 数据加载 =====
    function loadData() {
        if (!root.backend) return
        root.groupsData = root.clone(root.backend.get_groups())
        root.startDateText = root.backend.get_start_date()
        root.rotationMode = root.backend.get_rotation_mode()
        root.weekendMode = root.backend.get_weekend_mode()
        root.holidaysData = root.clone(root.backend.get_holidays())
        root.loadDisplayData()
        root.loadReminderData()
        var now = new Date()
        root.loadMonth(now.getFullYear(), now.getMonth() + 1)
        root.refreshTodayStats()
        root.bumpEdit()
    }

    function refreshTodayStats() {
        if (!root.backend) return
        root.todayData = root.backend.get_today_duty()
        root.statsData = root.backend.get_stats()
        root.weekSchedule = root.backend.get_week_schedule()
    }

    function bumpEdit() { root.editRev++ }

    // ===== 分组/成员编辑 =====
    function groupNamesList() {
        root.editRev
        var out = []
        for (var i = 0; i < root.groupsData.length; i++)
            out.push(root.groupsData[i].name || qsTr("第%1组").arg(i + 1))
        return out
    }

    function groupAt(gi) { return root.groupsData[gi] || null }

    function memberField(gi, mi, field) {
        root.editRev
        var g = root.groupsData[gi]
        return (g && g.members && g.members[mi]) ? (g.members[mi][field] || "") : ""
    }

    function setMemberField(gi, mi, field, value) {
        var g = root.groupsData[gi]
        if (g && g.members && g.members[mi]) g.members[mi][field] = value
    }

    function membersOfCurrent() {
        root.editRev
        var g = root.groupsData[root.currentGroupIndex]
        return (g && g.members) ? g.members : []
    }

    function addMember() {
        var g = root.groupAt(root.currentGroupIndex)
        if (!g) return
        g.members.push({ name: "", task: "" })
        root.groupsData = root.groupsData.slice()
        root.bumpEdit()
    }

    function removeMember(memberIndex) {
        var g = root.groupAt(root.currentGroupIndex)
        if (!g) return
        g.members.splice(memberIndex, 1)
        root.groupsData = root.groupsData.slice()
        root.bumpEdit()
    }

    function removeGroup(groupIndex) {
        var arr = root.groupsData.slice()
        arr.splice(groupIndex, 1)
        root.groupsData = arr
        if (root.currentGroupIndex >= arr.length)
            root.currentGroupIndex = Math.max(0, arr.length - 1)
        root.bumpEdit()
    }

    function addGroup() {
        var arr = root.groupsData.slice()
        arr.push({ name: qsTr("第%1组").arg(arr.length + 1), members: [] })
        root.groupsData = arr
        root.currentGroupIndex = arr.length - 1
        root.bumpEdit()
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
        if (added > 0) {
            root.groupsData = root.groupsData.slice()
            root.bumpEdit()
        }
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

    // 周末处理方式（仅工作日轮换生效）
    function applyWeekendMode(mode) {
        if (!root.backend || root.weekendMode === mode) return
        var ok = false
        try {
            ok = root.backend.save_weekend_mode(mode)
        } catch (e) {
            console.error("[值日生] 周末处理方式保存失败: " + e)
        }
        if (!ok) {
            rotationResultText.text = qsTr("保存失败：周末处理方式无效")
            rotationResultText.color = "#E5594F"
            return
        }
        root.weekendMode = mode
        rotationResultText.text = qsTr("周末处理已保存 ") + root.saveStamp()
        rotationResultText.color = "#2E7D32"
        root.refreshTodayStats()
        root.loadMonth(root.calYear, root.calMonth)
    }

    // ===== 假期 / 月历 =====
    function validDate(s) {
        return /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(new Date(s).getTime())
    }

    function reloadHolidays() {
        root.holidaysData = root.clone(root.backend.get_holidays())
        root.refreshTodayStats()
    }

    function addHoliday(start, end, name) {
        if (!root.validDate(start)) return false
        if (!end || !root.validDate(end)) end = start
        var arr = root.holidaysData.concat([{ start: start, end: end, name: name }])
        if (root.backend.save_holidays(JSON.stringify(arr))) {
            root.reloadHolidays()
            root.loadMonth(root.calYear, root.calMonth)
            return true
        }
        return false
    }

    function removeHoliday(index) {
        var arr = root.holidaysData.filter(function(_, i) { return i !== index })
        if (root.backend.save_holidays(JSON.stringify(arr))) {
            root.reloadHolidays()
            root.loadMonth(root.calYear, root.calMonth)
        }
    }

    function loadMonth(y, mth) {
        if (!root.backend) return
        root.monthInfo = root.clone(root.backend.get_month_info(y, mth))
        root.calYear = root.monthInfo.year
        root.calMonth = root.monthInfo.month
    }

    function calShift(delta) {
        var y = root.calYear, m = root.calMonth + delta
        if (m < 1) { m = 12; y-- } else if (m > 12) { m = 1; y++ }
        root.loadMonth(y, m)
    }

    function selectedInfo() {
        if (!root.selectedDate) return null
        var days = root.monthInfo.days || []
        for (var i = 0; i < days.length; i++)
            if (days[i].date === root.selectedDate) return days[i]
        return null
    }

    function selectedHasSingleHoliday() {
        for (var i = 0; i < root.holidaysData.length; i++) {
            var h = root.holidaysData[i]
            if (h.start === root.selectedDate && h.end === root.selectedDate)
                return true
        }
        return false
    }

    function selectedCoveredByRange() {
        for (var i = 0; i < root.holidaysData.length; i++) {
            var h = root.holidaysData[i]
            if (h.start <= root.selectedDate && root.selectedDate <= h.end)
                return true
        }
        return false
    }

    function toggleSelectedHoliday() {
        if (!root.selectedDate || !root.backend) return false
        var arr = [], removed = false
        for (var i = 0; i < root.holidaysData.length; i++) {
            var h = root.holidaysData[i]
            if (!removed && h.start === root.selectedDate && h.end === root.selectedDate) {
                removed = true
                continue
            }
            arr.push(h)
        }
        if (!removed) {
            if (root.selectedCoveredByRange()) return false  // 多日假期覆盖，请在区间列表调整
            arr.push({ start: root.selectedDate, end: root.selectedDate, name: "" })
        }
        if (!root.backend.save_holidays(JSON.stringify(arr))) return false
        root.reloadHolidays()
        root.loadMonth(root.calYear, root.calMonth)
        return true
    }

    function applyTempSwap(day, groupIndex) {
        if (!root.backend) return false
        var ok = root.backend.set_temp_swap(day, groupIndex)
        if (ok) {
            root.refreshTodayStats()
            root.loadMonth(root.calYear, root.calMonth)
        }
        return ok
    }

    // ===== 考勤 =====
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

    // ===== 界面预览（模拟部件普通模式）=====
    function previewPeriod() {
        if (!root.todayData) return qsTr("第 1 周")
        var n = root.todayData.periodNumber || 1
        if (root.todayData.rotationMode === "daily") return qsTr("第 %1 天").arg(n)
        if (root.todayData.rotationMode === "workday") return qsTr("第 %1 轮").arg(n)
        return qsTr("第 %1 周").arg(n)
    }

    function previewName(m) {
        if (!root.showName) return ""
        var nm = (m.name && m.name.length > 0) ? m.name : qsTr("（未命名）")
        if (m.status === "absent") nm += qsTr("（假）")
        return nm
    }

    function previewTask(m) {
        return root.showTask ? (m.task || "") : ""
    }

    function previewPair(m) {
        var nm = root.previewName(m), t = root.previewTask(m)
        if (nm && t) {
            if (root.pairStyle === "dot") return nm + "·" + t
            if (root.pairStyle === "taskfirst") return t + "：" + nm
            return nm + qsTr("（%1）").arg(t)
        }
        return nm || t || "—"
    }

    function previewRows() {
        var ms = (root.todayData && root.todayData.members) ? root.todayData.members : []
        if (root.pairStyle === "columns") return []
        var out = []
        if (root.memberLayout === "inline") {
            var labels = []
            for (var i = 0; i < ms.length; i++) labels.push(root.previewPair(ms[i]))
            out.push({ task: "", names: [labels.join("、")] })
            return out
        }
        var taskIndex = ({})
        for (var j = 0; j < ms.length; j++) {
            var m = ms[j]
            if (root.memberLayout === "person") {
                out.push({ task: "", names: [root.previewPair(m)] })
            } else if (root.previewTask(m)) {
                var t = root.previewTask(m), nm = root.previewName(m)
                if (taskIndex[t] === undefined) {
                    taskIndex[t] = out.length
                    out.push({ task: t, names: nm ? [nm] : [] })
                } else if (nm) {
                    out[taskIndex[t]].names.push(nm)
                }
            } else {
                var nm2 = root.previewName(m)
                if (nm2) out.push({ task: "", names: [nm2] })
            }
        }
        return out.filter(function(r) { return r.task !== "" || r.names.length > 0 })
    }

    function previewColumnRows() {
        if (root.pairStyle !== "columns") return []
        var ms = (root.todayData && root.todayData.members) ? root.todayData.members : []
        var out = []
        var taskIndex = ({})
        for (var i = 0; i < ms.length; i++) {
            var m = ms[i], nm = root.previewName(m), tk = root.previewTask(m)
            if (root.memberLayout === "task" && tk) {
                if (taskIndex[tk] === undefined) {
                    taskIndex[tk] = out.length
                    out.push({ left: tk, right: nm, isTask: true })
                } else if (nm) {
                    var prev = out[taskIndex[tk]].right
                    out[taskIndex[tk]].right = prev ? (prev + "、" + nm) : nm
                }
            } else {
                if (!nm && !tk) continue
                out.push({ left: nm || "—", right: tk, isTask: false })
            }
        }
        return out
    }

    onBackendChanged: loadData()
    Component.onCompleted: Qt.callLater(loadData)

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
            // 页面 0：界面设置（组件显隐 + 大小 + 显示方式 + 预览）
            // =====================================================
            ColumnLayout {
                visible: root.currentPage === 0
                spacing: 12
                Layout.fillWidth: true

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_text_font_size_20_regular"
                    title: qsTr("组件管理")
                    description: qsTr("分别控制组名、姓名、职责、次数在部件中的显示与字号（9~28px）")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        ComponentVisRow {
                            labelText: qsTr("组名")
                            visibleFlag: root.showGroup
                            sizeValue: root.fontGroup
                            onVisToggled: { root.showGroup = checked; root.pushDisplaySettings() }
                            onSizeMoved: { root.fontGroup = value; root.pushDisplaySettings() }
                        }
                        ComponentVisRow {
                            labelText: qsTr("姓名")
                            visibleFlag: root.showName
                            sizeValue: root.fontName
                            onVisToggled: { root.showName = checked; root.pushDisplaySettings() }
                            onSizeMoved: { root.fontName = value; root.pushDisplaySettings() }
                        }
                        ComponentVisRow {
                            labelText: qsTr("职责")
                            visibleFlag: root.showTask
                            sizeValue: root.fontTask
                            onVisToggled: { root.showTask = checked; root.pushDisplaySettings() }
                            onSizeMoved: { root.fontTask = value; root.pushDisplaySettings() }
                        }
                        ComponentVisRow {
                            labelText: qsTr("次数")
                            visibleFlag: root.showMeta
                            sizeValue: root.fontMeta
                            onVisToggled: { root.showMeta = checked; root.pushDisplaySettings() }
                            onSizeMoved: { root.fontMeta = value; root.pushDisplaySettings() }
                        }
                    }
                }

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_options_20_regular"
                    title: qsTr("显示方式")
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
                                currentIndex: root.pairStyleIndex()
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

                // ---------- 实时预览 ----------
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
                            spacing: 8

                            Icon { name: "ic_fluent_eye_20_regular"; size: 20 }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Text {
                                    text: qsTr("预览")
                                    font.pixelSize: 14
                                    color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: qsTr("按当前显示设置模拟部件普通模式的效果")
                                    font.pixelSize: 12
                                    color: Theme.currentTheme.colors.textSecondaryColor
                                    wrapMode: Text.Wrap
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: previewInner.implicitHeight + 24
                            radius: 8
                            color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.05) : Qt.alpha("#000000", 0.03)

                            ColumnLayout {
                                id: previewInner
                                anchors.centerIn: parent
                                width: parent.width - 24
                                spacing: 6

                                // 头部：组名胶囊 + 次数 + 假期徽标
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    visible: root.showGroup || root.showMeta
                                             || (root.todayData && root.todayData.isHoliday)

                                    Rectangle {
                                        visible: root.showGroup
                                        Layout.preferredHeight: Math.max(22, previewGroupText.implicitHeight + 10)
                                        Layout.preferredWidth: previewGroupText.implicitWidth + 22
                                        radius: height / 2
                                        color: Colors.proxy.primaryColor

                                        Text {
                                            id: previewGroupText
                                            anchors.centerIn: parent
                                            text: root.todayData ? root.todayData.groupName : qsTr("第1组")
                                            color: "#FFFFFF"
                                            font.pixelSize: root.fontGroup
                                            font.weight: Font.DemiBold
                                        }
                                    }

                                    Text {
                                        visible: root.showMeta
                                        text: root.previewPeriod()
                                        font.pixelSize: root.fontMeta
                                        opacity: 0.6
                                    }

                                    Rectangle {
                                        visible: root.todayData && root.todayData.isHoliday
                                        Layout.preferredHeight: Math.max(18, previewHolidayText.implicitHeight + 8)
                                        Layout.preferredWidth: previewHolidayText.implicitWidth + 14
                                        radius: height / 2
                                        color: "#E5A100"

                                        Text {
                                            id: previewHolidayText
                                            anchors.centerIn: parent
                                            text: (root.todayData && root.todayData.holidayName)
                                                  ? root.todayData.holidayName : qsTr("假期中")
                                            color: "#FFFFFF"
                                            font.pixelSize: root.fontMeta
                                        }
                                    }

                                    Item { Layout.fillWidth: true }
                                }

                                // 成员区：非两列模式
                                Repeater {
                                    model: root.previewRows()

                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 8

                                        Text {
                                            visible: modelData.task !== ""
                                            text: modelData.task ? modelData.task + "：" : ""
                                            font.pixelSize: root.fontTask
                                            font.weight: Font.DemiBold
                                            color: Colors.proxy.primaryColor
                                        }

                                        Text {
                                            text: modelData.names.join("、")
                                            font.pixelSize: root.fontName
                                            font.weight: modelData.task !== "" ? Font.Normal : Font.DemiBold
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                            color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                                        }

                                        Item { Layout.fillWidth: true }
                                    }
                                }

                                // 成员区：两列对齐
                                Repeater {
                                    model: root.previewColumnRows()

                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 8

                                        Text {
                                            text: modelData.left
                                            font.pixelSize: modelData.isTask ? root.fontTask : root.fontName
                                            font.weight: Font.DemiBold
                                            color: modelData.isTask
                                                   ? Colors.proxy.primaryColor
                                                   : (Theme.isDark() ? "#FFFFFF" : "#1B1B1F")
                                            elide: Text.ElideRight
                                            Layout.preferredWidth: 110
                                        }

                                        Text {
                                            visible: modelData.right !== ""
                                            text: modelData.right
                                            font.pixelSize: root.fontTask
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                            color: Theme.isDark()
                                                   ? Qt.alpha("#FFFFFF", 0.6)
                                                   : Qt.alpha("#000000", 0.55)
                                        }

                                        Item { Layout.fillWidth: true }
                                    }
                                }

                                Text {
                                    visible: root.previewRows().length === 0
                                             && root.previewColumnRows().length === 0
                                    text: qsTr("（今日暂无值日成员，预览为空）")
                                    font.pixelSize: 12
                                    opacity: 0.5
                                }
                            }
                        }
                    }
                }
            }

            // =====================================================
            // 页面 1：人员设置（组别管理）
            // =====================================================
            ColumnLayout {
                visible: root.currentPage === 1
                spacing: 12
                Layout.fillWidth: true

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_people_20_regular"
                    title: qsTr("组别管理")
                    description: qsTr("选择要编辑的值日小组；修改组名与成员后点击保存")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            ComboBox {
                                id: groupCombo
                                Layout.preferredWidth: 180
                                model: root.groupNamesList()
                                currentIndex: root.currentGroupIndex
                                onActivated: {
                                    root.currentGroupIndex = index
                                    root.bumpEdit()
                                }
                            }

                            Item { Layout.fillWidth: true }

                            Button {
                                text: qsTr("保存人员设置")
                                highlighted: true
                                onClicked: {
                                    root.doSave()
                                    root.refreshTodayStats()
                                    peopleResultText.text = qsTr("保存成功 ") + root.saveStamp()
                                    peopleResultText.color = "#2E7D32"
                                }
                            }
                        }

                        ResultText { id: peopleResultText }
                    }
                }

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_edit_20_regular"
                    title: qsTr("组名与成员")
                    description: qsTr("组名修改后点击确认；成员支持批量快速导入")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Label { text: qsTr("组名"); opacity: 0.7; font.pixelSize: 12 }
                            TextField {
                                id: groupNameField
                                Layout.preferredWidth: 180
                                placeholderText: qsTr("组名")
                                text: {
                                    root.editRev
                                    var g = root.groupAt(root.currentGroupIndex)
                                    return g ? g.name : ""
                                }
                                onTextEdited: {
                                    var g = root.groupAt(root.currentGroupIndex)
                                    if (g) g.name = text
                                }
                            }

                            Button {
                                text: qsTr("确认")
                                onClicked: {
                                    root.doSave()
                                    root.refreshTodayStats()
                                    root.bumpEdit()
                                    groupResultText.text = qsTr("组名已更新 ") + root.saveStamp()
                                    groupResultText.color = "#2E7D32"
                                }
                            }

                            Button {
                                text: qsTr("删除该组")
                                enabled: root.groupsData.length > 0
                                onClicked: root.removeGroup(root.currentGroupIndex)
                            }

                            Button {
                                text: qsTr("快速导入")
                                onClicked: importPopup.open()
                            }

                            Button {
                                text: qsTr("新建组")
                                highlighted: true
                                onClicked: root.addGroup()
                            }

                            Item { Layout.fillWidth: true }
                        }

                        ResultText { id: groupResultText }

                        // 成员列表：序号 | 姓名 | 职责 | 移除
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            visible: root.membersOfCurrent().length > 0

                            Text { text: qsTr("#"); Layout.preferredWidth: 24; opacity: 0.5; font.pixelSize: 12 }
                            Text { text: qsTr("姓名"); Layout.fillWidth: true; opacity: 0.5; font.pixelSize: 12 }
                            Text { text: qsTr("职责"); Layout.fillWidth: true; opacity: 0.5; font.pixelSize: 12 }
                            Item { Layout.preferredWidth: 64 }
                        }

                        Repeater {
                            model: root.membersOfCurrent()

                            delegate: RowLayout {
                                required property int index

                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    text: index + 1
                                    Layout.preferredWidth: 24
                                    opacity: 0.5
                                    font.pixelSize: 12
                                    horizontalAlignment: Text.AlignHCenter
                                }

                                TextField {
                                    Layout.fillWidth: true
                                    placeholderText: qsTr("姓名")
                                    text: root.memberField(root.currentGroupIndex, index, "name")
                                    onTextEdited: root.setMemberField(root.currentGroupIndex, index, "name", text)
                                }

                                TextField {
                                    Layout.fillWidth: true
                                    placeholderText: qsTr("任务，如：扫地")
                                    text: root.memberField(root.currentGroupIndex, index, "task")
                                    onTextEdited: root.setMemberField(root.currentGroupIndex, index, "task", text)
                                }

                                Button {
                                    Layout.preferredWidth: 64
                                    text: qsTr("移除")
                                    onClicked: root.removeMember(index)
                                }
                            }
                        }

                        Text {
                            visible: root.membersOfCurrent().length === 0
                            text: qsTr("当前组还没有成员，点击下方按钮新增或快速导入")
                            opacity: 0.55
                            font.pixelSize: 12
                        }

                        Button {
                            text: qsTr("+ 新增成员")
                            onClicked: root.addMember()
                        }
                    }
                }

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_table_20_regular"
                    title: qsTr("配置表")
                    description: qsTr("以通用 JSON 导入/导出分组与轮换配置；排班表为组别+成员+职责的 CSV 格式")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Button {
                                text: qsTr("导入配置表")
                                onClicked: importConfigPopup.open()
                            }

                            Button {
                                text: qsTr("导出配置表")
                                onClicked: {
                                    var r = root.backend.export_config(configTablePathField.text)
                                    configTableResultText.text = r.ok ? qsTr("已导出到：") + r.msg : qsTr("导出失败：") + r.msg
                                    configTableResultText.color = r.ok ? "#2E7D32" : "#E5594F"
                                }
                            }

                            Button {
                                text: qsTr("写出值日排班表")
                                onClicked: {
                                    var r = root.backend.export_schedule(4)
                                    configTableResultText.text = r.msg
                                    configTableResultText.color = r.ok ? "#2E7D32" : "#E5594F"
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }

                        TextField {
                            id: configTablePathField
                            Layout.fillWidth: true
                            text: "~/Desktop/duty_config.json"
                            placeholderText: qsTr("配置表路径，支持 ~")
                        }

                        ResultText { id: configTableResultText }
                    }
                }
            }

            // =====================================================
            // 页面 2：轮换管理（轮换配置 + 起始日 + 月历 + 预览 + 导出）
            // =====================================================
            ColumnLayout {
                visible: root.currentPage === 2
                spacing: 12
                Layout.fillWidth: true

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_arrow_sync_20_regular"
                    title: qsTr("轮换配置")
                    description: qsTr("选择轮换周期；工作日轮换可单独设置周末的处理方式")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        RowLayout {
                            spacing: 12

                            RadioButton {
                                text: qsTr("每日轮换")
                                checked: root.rotationMode === "daily"
                                onClicked: {
                                    if (root.rotationMode === "daily") return
                                    root.rotationMode = "daily"
                                    root.doSave()
                                    root.refreshTodayStats()
                                    rotationResultText.text = qsTr("已切换为每日轮换 ") + root.saveStamp()
                                    rotationResultText.color = "#2E7D32"
                                }
                            }
                            RadioButton {
                                text: qsTr("工作日轮换")
                                checked: root.rotationMode === "workday"
                                onClicked: {
                                    if (root.rotationMode === "workday") return
                                    root.rotationMode = "workday"
                                    root.doSave()
                                    root.refreshTodayStats()
                                    rotationResultText.text = qsTr("已切换为工作日轮换 ") + root.saveStamp()
                                    rotationResultText.color = "#2E7D32"
                                }
                            }
                            RadioButton {
                                text: qsTr("每周轮换")
                                checked: root.rotationMode === "weekly"
                                onClicked: {
                                    if (root.rotationMode === "weekly") return
                                    root.rotationMode = "weekly"
                                    root.doSave()
                                    root.refreshTodayStats()
                                    rotationResultText.text = qsTr("已切换为每周轮换 ") + root.saveStamp()
                                    rotationResultText.color = "#2E7D32"
                                }
                            }
                        }

                        RowLayout {
                            spacing: 12
                            visible: root.rotationMode === "workday"

                            Label { text: qsTr("周末处理"); opacity: 0.7; font.pixelSize: 12 }
                            RadioButton {
                                text: qsTr("合并计一天")
                                checked: root.weekendMode === "merge"
                                onClicked: root.applyWeekendMode("merge")
                            }
                            RadioButton {
                                text: qsTr("周末不轮换")
                                checked: root.weekendMode === "skip"
                                onClicked: root.applyWeekendMode("skip")
                            }
                            RadioButton {
                                text: qsTr("周末逐日计档")
                                checked: root.weekendMode === "each"
                                onClicked: root.applyWeekendMode("each")
                            }
                        }

                        ResultText { id: rotationResultText }
                    }
                }

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_calendar_start_20_regular"
                    title: qsTr("轮换起始日期")
                    description: qsTr("轮换从此日期开始计数；失焦或回车自动保存")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        RowLayout {
                            spacing: 8

                            TextField {
                                id: startField
                                text: root.startDateText
                                placeholderText: "YYYY-MM-DD"
                                onTextEdited: root.startDateText = text
                                onEditingFinished: {
                                    if (root.validDate(root.startDateText)) {
                                        root.doSave()
                                        root.refreshTodayStats()
                                        startResultText.text = qsTr("保存成功 ") + root.saveStamp()
                                        startResultText.color = "#2E7D32"
                                    } else {
                                        startResultText.text = qsTr("日期格式应为 YYYY-MM-DD")
                                        startResultText.color = "#E5594F"
                                    }
                                }
                            }

                            Button {
                                text: qsTr("设为今天")
                                onClicked: {
                                    var d = new Date()
                                    var mm = String(d.getMonth() + 1).padStart(2, "0")
                                    var dd = String(d.getDate()).padStart(2, "0")
                                    root.startDateText = d.getFullYear() + "-" + mm + "-" + dd
                                    startField.text = root.startDateText
                                    root.doSave()
                                    root.refreshTodayStats()
                                    startResultText.text = qsTr("已设为今天 ") + root.saveStamp()
                                    startResultText.color = "#2E7D32"
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }

                        ResultText { id: startResultText }
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
                                    holidayResultText.text = ok ? qsTr("已添加假期") : qsTr("添加失败：日期格式应为 YYYY-MM-DD")
                                    holidayResultText.color = ok ? "#2E7D32" : "#E5594F"
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

                        ResultText { id: holidayResultText }
                    }
                }

                // ---------- 月历：点选日期 → 放假 / 临时调班 ----------
                Frame {
                    Layout.fillWidth: true
                    leftPadding: 18
                    rightPadding: 18
                    topPadding: 16
                    bottomPadding: 16

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            Icon { name: "ic_fluent_calendar_ltr_20_regular"; size: 20 }
                            Text {
                                text: root.calYear > 0 ? root.calYear + qsTr("年") + root.calMonth + qsTr("月") : qsTr("加载中…")
                                font.pixelSize: 14
                                color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                            }
                            Button {
                                text: qsTr("←")
                                onClicked: root.calShift(-1)
                            }
                            Button {
                                text: qsTr("→")
                                onClicked: root.calShift(1)
                            }
                            Button {
                                text: qsTr("本月")
                                onClicked: {
                                    var d = new Date()
                                    root.loadMonth(d.getFullYear(), d.getMonth() + 1)
                                }
                            }
                            Item { Layout.fillWidth: true }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 7
                            rowSpacing: 4
                            columnSpacing: 4

                            Repeater {
                                model: [qsTr("一"), qsTr("二"), qsTr("三"), qsTr("四"), qsTr("五"), qsTr("六"), qsTr("日")]

                                delegate: Text {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    text: modelData
                                    font.pixelSize: 11
                                    opacity: 0.5
                                }
                            }

                            Repeater {
                                model: root.monthInfo.days

                                delegate: Rectangle {
                                    id: calCell
                                    required property var modelData

                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    Layout.preferredHeight: 34
                                    radius: 6
                                    property bool selected: root.selectedDate === modelData.date

                                    color: selected
                                           ? (Theme.isDark() ? Qt.alpha(Colors.proxy.primaryColor, 0.35) : Qt.alpha(Colors.proxy.primaryColor, 0.25))
                                           : modelData.holidayName
                                             ? (Theme.isDark() ? Qt.alpha("#E5A100", 0.25) : "#FFF5DC")
                                             : modelData.isToday
                                               ? (Theme.isDark() ? Qt.alpha("#FFFFFF", 0.12) : Qt.alpha("#000000", 0.08))
                                               : (Theme.isDark() ? Qt.alpha("#FFFFFF", 0.04) : "transparent")
                                    border.width: selected ? 1 : (modelData.isSwap ? 1 : 0)
                                    border.color: selected ? Colors.proxy.primaryColor : "#E5A100"
                                    opacity: modelData.inMonth ? 1.0 : 0.35

                                    Text {
                                        anchors.centerIn: parent
                                        text: calCell.modelData.day
                                        font.pixelSize: 12
                                        font.bold: calCell.modelData.isToday
                                        color: Theme.isDark() ? "#FFFFFF" : "#1B1B1F"
                                    }

                                    Rectangle {
                                        anchors.bottom: parent.bottom
                                        anchors.bottomMargin: 3
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: 5; height: 5; radius: 2.5
                                        visible: calCell.modelData.isSwap
                                        color: "#E5A100"
                                    }

                                    TapHandler {
                                        onTapped: root.selectedDate = calCell.modelData.date
                                    }
                                }
                            }
                        }

                        // 选中日期的操作区
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            visible: root.selectedDate !== ""

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                Text {
                                    text: root.selectedDate
                                    font.pixelSize: 13
                                    font.bold: true
                                }
                                Text {
                                    text: {
                                        var info = root.selectedInfo()
                                        if (!info) return ""
                                        var s = info.groupName ? qsTr("值日：") + info.groupName : ""
                                        if (info.holidayName) s += (s ? " · " : "") + info.holidayName
                                        if (info.isSwap && info.autoGroupName)
                                            s += (s ? " · " : "") + qsTr("原：") + info.autoGroupName
                                        return s
                                    }
                                    font.pixelSize: 12
                                    opacity: 0.7
                                }
                                Item { Layout.fillWidth: true }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                CheckBox {
                                    id: calHolidayCheck
                                    text: qsTr("该日放假")
                                    checked: root.selectedHasSingleHoliday()
                                    onToggled: {
                                        var ok = root.toggleSelectedHoliday()
                                        if (!ok) {
                                            calHolidayCheck.checked = root.selectedHasSingleHoliday()
                                            calResultText.text = root.selectedCoveredByRange()
                                                  ? qsTr("该日在多日假期内，请在上方假期列表中调整")
                                                  : qsTr("操作失败")
                                            calResultText.color = "#E5594F"
                                            return
                                        }
                                        calResultText.text = qsTr("已更新 ") + root.saveStamp()
                                        calResultText.color = "#2E7D32"
                                    }
                                }

                                Label { text: qsTr("临时调为"); opacity: 0.7; font.pixelSize: 12 }
                                ComboBox {
                                    id: calSwapCombo
                                    Layout.preferredWidth: 140
                                    model: root.groupNamesList()
                                }
                                Button {
                                    text: qsTr("应用调班")
                                    onClicked: {
                                        var ok = root.applyTempSwap(root.selectedDate, calSwapCombo.currentIndex)
                                        calResultText.text = ok ? qsTr("已设置调班 ") + root.saveStamp() : qsTr("设置失败：请先新建分组")
                                        calResultText.color = ok ? "#2E7D32" : "#E5594F"
                                    }
                                }
                                Button {
                                    text: qsTr("清除调班")
                                    onClicked: {
                                        var ok = root.applyTempSwap(root.selectedDate, -1)
                                        calResultText.text = ok ? qsTr("已清除调班") : qsTr("清除失败")
                                        calResultText.color = ok ? "#2E7D32" : "#E5594F"
                                    }
                                }
                                Item { Layout.fillWidth: true }
                            }

                            ResultText { id: calResultText }
                        }
                    }
                }

                // ---------- 本周值日预览 ----------
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
                                name: "ic_fluent_calendar_week_numbers_20_regular"
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

                // ---------- 值日表导出 ----------
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
            }

            // =====================================================
            // 页面 3：请假管理（今日请假 + 手动换组 + 统计）
            // =====================================================
            ColumnLayout {
                visible: root.currentPage === 3
                spacing: 12
                Layout.fillWidth: true

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_person_prohibited_20_regular"
                    title: qsTr("今日请假")
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
                    description: qsTr("自动记录每日值日与请假，手动换组会标记为“调换”")

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
            // 页面 4：实验性功能
            // =====================================================
            ColumnLayout {
                visible: root.currentPage === 4
                spacing: 12
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: qsTr("此页功能较新，后续版本可能调整或移除")
                    opacity: 0.55
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
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
            // 页面 5：备份 / 迁移
            // =====================================================
            ColumnLayout {
                visible: root.currentPage === 5
                spacing: 12
                Layout.fillWidth: true

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_arrow_import_20_regular"
                    title: qsTr("备份内容")
                    description: qsTr("勾选需要导出或导入的内容；备份为通用 JSON 文件")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        CheckBox {
                            text: qsTr("界面设置（组件显隐、字号、显示方式）")
                            checked: root.backupDisplay
                            onToggled: root.backupDisplay = checked
                        }
                        CheckBox {
                            text: qsTr("人员设置（分组与成员）")
                            checked: root.backupPeople
                            onToggled: root.backupPeople = checked
                        }
                        CheckBox {
                            text: qsTr("轮换配置及方式（起始日、周期、假期、临时调班）")
                            checked: root.backupRotation
                            onToggled: root.backupRotation = checked
                        }
                        CheckBox {
                            text: qsTr("请假记录（每日考勤与统计）")
                            checked: root.backupHistory
                            onToggled: root.backupHistory = checked
                        }
                    }
                }

                SettingCard {
                    Layout.fillWidth: true
                    icon.name: "ic_fluent_save_20_regular"
                    title: qsTr("导出 / 导入")
                    description: qsTr("导出勾选内容到备份文件；导入时仅恢复勾选的分节")

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        TextField {
                            id: backupPathField
                            Layout.fillWidth: true
                            text: "~/Desktop/duty_backup.json"
                            placeholderText: qsTr("备份文件路径，支持 ~")
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Button {
                                text: qsTr("导出备份")
                                onClicked: {
                                    var r = root.backend.export_backup(
                                        backupPathField.text,
                                        root.backupDisplay, root.backupPeople,
                                        root.backupRotation, root.backupHistory
                                    )
                                    backupResultText.text = r.ok ? qsTr("已导出到：") + r.msg : qsTr("导出失败：") + r.msg
                                    backupResultText.color = r.ok ? "#2E7D32" : "#E5594F"
                                }
                            }

                            Button {
                                text: qsTr("导入备份")
                                highlighted: true
                                onClicked: {
                                    var r = root.backend.import_backup(
                                        backupPathField.text,
                                        root.backupDisplay, root.backupPeople,
                                        root.backupRotation, root.backupHistory
                                    )
                                    backupResultText.text = r.ok ? r.msg : qsTr("导入失败：") + r.msg
                                    backupResultText.color = r.ok ? "#2E7D32" : "#E5594F"
                                    if (r.ok) root.loadData()
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }

                        ResultText { id: backupResultText }
                    }
                }
            }
        }
    }

    // ============================================================
    // 公共组件
    // ============================================================

    // 组件显隐 + 字号一行（界面设置页）
    component ComponentVisRow: RowLayout {
        id: visRow
        property string labelText: ""
        property bool visibleFlag: true
        property int sizeValue: 12
        signal visToggled(bool checked)
        signal sizeMoved(int value)

        Layout.fillWidth: true
        spacing: 10

        Text {
            text: visRow.labelText
            opacity: 0.7
            font.pixelSize: 12
            Layout.preferredWidth: 48
        }
        Switch {
            text: visRow.visibleFlag ? qsTr("显示") : qsTr("隐藏")
            checked: visRow.visibleFlag
            onToggled: visRow.visToggled(checked)
        }
        Slider {
            Layout.fillWidth: true
            from: 9
            to: 28
            stepSize: 1
            value: visRow.sizeValue
            enabled: visRow.visibleFlag
            onMoved: visRow.sizeMoved(Math.round(value))
        }
        Text {
            text: visRow.sizeValue + " px"
            font.pixelSize: 12
            Layout.preferredWidth: 44
            horizontalAlignment: Text.AlignRight
            opacity: visRow.visibleFlag ? 1 : 0.4
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
    // 弹窗
    // ============================================================

    // 快速导入成员（作用于当前组）
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
                text: qsTr("每行一个成员，导入到当前选中的组。格式：\n  姓名 任务\n  姓名,任务\n  姓名（仅姓名）")
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
                        root.importMembers(root.currentGroupIndex, importArea.text)
                        importArea.text = ""
                        importPopup.close()
                    }
                }
            }
        }
    }

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

    // 导入配置表路径弹窗
    Popup {
        id: importConfigPopup
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
                text: qsTr("导入配置表")
                font.bold: true
                font.pixelSize: 16
            }

            Text {
                Layout.fillWidth: true
                text: qsTr("输入导出的配置表 JSON 路径；导入后分组、轮换与假期将被覆盖")
                color: "#888"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }

            TextField {
                id: importConfigPathField
                Layout.fillWidth: true
                text: configTablePathField.text
                placeholderText: qsTr("配置表路径，支持 ~")
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item { Layout.fillWidth: true }

                Button {
                    text: qsTr("取消")
                    onClicked: importConfigPopup.close()
                }

                Button {
                    text: qsTr("导入")
                    highlighted: true
                    onClicked: {
                        var r = root.backend.import_config(importConfigPathField.text)
                        configTableResultText.text = r.ok ? r.msg : qsTr("导入失败：") + r.msg
                        configTableResultText.color = r.ok ? "#2E7D32" : "#E5594F"
                        if (r.ok) root.loadData()
                        importConfigPopup.close()
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
