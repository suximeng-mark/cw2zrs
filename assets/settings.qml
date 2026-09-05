import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: root
    clip: true

    property var groupsData: []
    property string startDateText: "2025-09-01"

    function loadData() {
        groupsData = backend.get_groups()
        startDateText = backend.get_start_date()
        rebuild()
    }

    ColumnLayout {
        id: mainColumn
        x: 16
        width: root.width - 32
        spacing: 12

        // 顶部占位
        Item { Layout.preferredHeight: 12 }

        // 标题
        Text {
            text: "值日生设置"
            font.pixelSize: 18
            font.bold: true
        }

        // 起始日期
        GroupBox {
            title: "轮换起始日期"
            Layout.fillWidth: true

            RowLayout {
                width: parent.width
                spacing: 8

                Text { text: "起始日期" }

                TextField {
                    id: startDateField
                    Layout.fillWidth: true
                    placeholderText: "YYYY-MM-DD"
                    text: startDateText
                    onTextChanged: startDateText = text
                }

                Button {
                    text: "设为今天"
                    onClicked: {
                        var d = new Date()
                        var m = String(d.getMonth() + 1).padStart(2, "0")
                        var day = String(d.getDate()).padStart(2, "0")
                        startDateField.text = d.getFullYear() + "-" + m + "-" + day
                    }
                }
            }
        }

        // 分组列表容器
        ColumnLayout {
            id: groupsColumn
            Layout.fillWidth: true
            spacing: 10
        }

        // 添加分组
        Button {
            text: "+ 添加分组"
            onClicked: {
                groupsData.push({ name: "第" + (groupsData.length + 1) + "组", members: [] })
                rebuild()
            }
        }

        // 保存按钮
        Button {
            text: "保存设置"
            Layout.fillWidth: true
            highlighted: true
            onClicked: {
                backend.set_start_date(startDateField.text)
                backend.save_groups(JSON.stringify(groupsData))
            }
        }

        // 底部占位
        Item { Layout.preferredHeight: 16 }
    }

    function rebuild() {
        // 清空分组容器
        groupsColumn.children = []

        for (var gi = 0; gi < groupsData.length; gi++) {
            var group = groupsData[gi]

            var gb = Qt.createQmlObject(
                'import QtQuick; import QtQuick.Controls; GroupBox { Layout.fillWidth: true; }',
                groupsColumn, "groupBox" + gi
            )
            gb.title = "分组 " + (gi + 1)

            var col = Qt.createQmlObject(
                'import QtQuick; import QtQuick.Layouts; ColumnLayout { width: parent.width; spacing: 6; }',
                gb, "groupCol" + gi
            )

            // 组名
            var nameRow = Qt.createQmlObject(
                'import QtQuick; import QtQuick.Layouts; RowLayout { Layout.fillWidth: true; spacing: 6; }',
                col, "nameRow" + gi
            )
            Qt.createQmlObject('import QtQuick; Text { text: "组名"; }', nameRow, "nameLabel" + gi)
            var nameField = Qt.createQmlObject(
                'import QtQuick; import QtQuick.Controls; TextField { Layout.fillWidth: true; }',
                nameRow, "nameField" + gi
            )
            nameField.text = group.name || ""
            nameField.textChanged.connect(function(newText) {
                groupsData[gi].name = newText
            })
            var delGroupBtn = Qt.createQmlObject(
                'import QtQuick; import QtQuick.Controls; Button { text: "删除组"; }',
                nameRow, "delGroupBtn" + gi
            )
            delGroupBtn.clicked.connect((function(idx) {
                return function() {
                    groupsData.splice(idx, 1)
                    rebuild()
                }
            })(gi))

            // 成员列表
            var membersCol = Qt.createQmlObject(
                'import QtQuick; import QtQuick.Layouts; ColumnLayout { Layout.fillWidth: true; spacing: 4; }',
                col, "membersCol" + gi
            )

            for (var mi = 0; mi < group.members.length; mi++) {
                addMemberRow(membersCol, gi, mi, group.members[mi])
            }

            // 添加成员
            var addBtn = Qt.createQmlObject(
                'import QtQuick; import QtQuick.Controls; Button { text: "+ 添加成员"; }',
                col, "addBtn" + gi
            )
            addBtn.clicked.connect((function(idx) {
                return function() {
                    groupsData[idx].members.push({ name: "", task: "" })
                    rebuild()
                }
            })(gi))
        }
    }

    function addMemberRow(parent, gi, mi, member) {
        var row = Qt.createQmlObject(
            'import QtQuick; import QtQuick.Layouts; RowLayout { Layout.fillWidth: true; spacing: 4; }',
            parent, "memberRow" + gi + "_" + mi
        )

        var nameField = Qt.createQmlObject(
            'import QtQuick; import QtQuick.Controls; TextField { Layout.fillWidth: true; placeholderText: "姓名"; }',
            row, "mName" + gi + "_" + mi
        )
        nameField.text = member.name || ""
        nameField.textChanged.connect(function(newText) {
            groupsData[gi].members[mi].name = newText
        })

        var taskField = Qt.createQmlObject(
            'import QtQuick; import QtQuick.Controls; TextField { Layout.fillWidth: true; placeholderText: "任务（如扫地）"; }',
            row, "mTask" + gi + "_" + mi
        )
        taskField.text = member.task || ""
        taskField.textChanged.connect(function(newText) {
            groupsData[gi].members[mi].task = newText
        })

        var delBtn = Qt.createQmlObject(
            'import QtQuick; import QtQuick.Controls; Button { text: "删除"; }',
            row, "mDel" + gi + "_" + mi
        )
        delBtn.clicked.connect((function(gidx, midx) {
            return function() {
                groupsData[gidx].members.splice(midx, 1)
                rebuild()
            }
        })(gi, mi))
    }

    Component.onCompleted: loadData()
}
