# -*- coding: utf-8 -*-
"""值日表 xlsx 导出回归测试。

.xlsx 就是 zip + 一组 OOXML，这里校验三件事：
  1. zip 结构完整、六个必需部件齐全、每个部件都是合法 XML
  2. 行数与表头样式（加粗表头 + 冻结首行 + 自动筛选）
  3. 备注 → 行底色的分类（假期琥珀 / 周末居中 / 普通左对齐）与 XML 转义

运行方式（无需 CW2 环境）：
    python tests/test_export_xlsx.py
"""

import importlib.util
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tests"))
_spec = importlib.util.spec_from_file_location(
    "_rot", ROOT / "tests" / "test_rotation.py"
)
_rot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rot)  # 顺带装好 SDK/QtCore 桩并导入 main

m = _rot.m
Plugin = m.Plugin

PASS = 0
FAIL = 0

REQUIRED_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
    "xl/styles.xml",
    "xl/worksheets/sheet1.xml",
}


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got={got!r} want={want!r}")


def build_plugin(holidays=None, groups=("甲组", "乙组")):
    """最小可用的 Plugin（只需要导出相关的字段）。"""
    p = object.__new__(Plugin)
    p._groups = m.Plugin._parse_groups([
        {
            "name": g,
            "members": [
                {"name": f"{g}-甲", "task": "扫地"},
                {"name": f"{g}-乙", "task": "擦黑板"},
            ],
        }
        for g in groups
    ])
    p._holidays = m.Plugin._parse_holidays(holidays or [])
    p._holidays_fp = None
    p._holiday_idx = None
    p._merge_pairs = []
    p._merge_valid = None
    p._merge_index = None
    p._merge_ends = None
    p._start_date = "2026-03-02"
    p._start_day = m.Plugin._parse_date(p, "2026-03-02")
    p._rotation_mode = m.MODE_DAILY
    p._weekend_mode = "merge"
    p._slot_days = 1
    p._manual_offset = 0
    return p


def write_xlsx(p, rows, weeks=2):
    start = date(2026, 3, 2)
    out = Path(tempfile.gettempdir()) / "值日表_regression.xlsx"
    p._write_schedule_xlsx(out, rows, start, start + timedelta(days=weeks * 7 - 1), weeks)
    return out


def test_structure() -> None:
    p = build_plugin()
    rows = p._build_schedule_rows(date(2026, 3, 2), 2)
    path = write_xlsx(p, rows)
    with zipfile.ZipFile(path) as z:
        check("zip 完整性", z.testzip(), None)
        check("部件齐全", REQUIRED_PARTS.issubset(set(z.namelist())), True)
        for name in z.namelist():
            try:
                ET.fromstring(z.read(name))
                ok = True
            except ET.ParseError as e:  # pragma: no cover
                print(f"  XML 解析失败 {name}: {e}")
                ok = False
            check(f"XML 合法 {name}", ok, True)
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        styles = z.read("xl/styles.xml").decode("utf-8")

    check("行数 = 表头 + 天数", sheet.count("<row "), 1 + len(rows))
    check("首行是表头样式", f'<c r="A1" s="{Plugin.XLSX_HEADER}"' in sheet, True)
    check("冻结首行", 'state="frozen"' in sheet, True)
    check("自动筛选", '<autoFilter ref="A1:F15"' in sheet, True)
    check("列宽 6 列", sheet.count("<col "), len(Plugin.XLSX_WIDTHS))
    # cellXfs 里的条目数必须与 XLSX_* 常量一一对应
    # （整份 styles.xml 里还有 cellStyleXfs 的那一条，不能一并数进去）
    cell_xfs = styles.split("<cellXfs", 1)[1].split("</cellXfs>", 1)[0]
    check("cellXfs 数量", cell_xfs.count("<xf "), 6)


def test_row_styles() -> None:
    check("假期行", Plugin._schedule_row_style("假期：国庆"), Plugin.XLSX_HOLIDAY)
    check("周末行", Plugin._schedule_row_style("周末"), Plugin.XLSX_WEEKEND)
    check("普通行", Plugin._schedule_row_style(""), Plugin.XLSX_TEXT)
    check(
        "带合并备注的行按普通处理（与 HTML 版的判定保持一致）",
        Plugin._schedule_row_style("周末 · 与 2026-03-05 合并计 1 档"),
        Plugin.XLSX_TEXT,
    )

    p = build_plugin(holidays=[{"start": "2026-03-03", "end": "2026-03-04", "name": "春假"}])
    rows = p._build_schedule_rows(date(2026, 3, 2), 1)
    sheet = zipfile.ZipFile(write_xlsx(p, rows, 1)).read(
        "xl/worksheets/sheet1.xml"
    ).decode("utf-8")
    # 03-03 是假期 → 整行琥珀底；03-02 是周一 → 普通
    check("假期行整行同色", f's="{Plugin.XLSX_HOLIDAY}"' in sheet, True)
    check("普通行有左对齐样式", f's="{Plugin.XLSX_TEXT}"' in sheet, True)


def test_escape() -> None:
    check("转义 &", Plugin._xml_escape("A&B"), "A&amp;B")
    check("转义 <", Plugin._xml_escape("<x>"), "&lt;x&gt;")
    check("转义引号", Plugin._xml_escape('a"b'), "a&quot;b")

    p = build_plugin(groups=('A&B"<组>', "乙组"))
    rows = p._build_schedule_rows(date(2026, 3, 2), 1)
    sheet = zipfile.ZipFile(write_xlsx(p, rows, 1)).read(
        "xl/worksheets/sheet1.xml"
    ).decode("utf-8")
    check("组名已转义后确实写进了 sheet", sheet.count("A&amp;B&quot;&lt;组&gt;") > 0, True)
    check("无未转义的裸 &", "A&B" in sheet, False)


def main() -> int:
    test_structure()
    test_row_styles()
    test_escape()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())