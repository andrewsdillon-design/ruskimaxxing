import csv
import shutil
import subprocess
from datetime import date

import pytest
from openpyxl import load_workbook

from ruskimaxxing.excel import build_workbook
from ruskimaxxing.exercises import CATALOG

DATA = {"units": "lb", "increment": 5, "start": date(2026, 10, 5), "height": 70, "bodyweight_start": 178,
        "bodyfat_start": 19, "bodyfat_method": "Bod Pod",
        "baseline": [("Squat", 250, 5), ("Bench Press", 185, 1), ("2-Board Press", 200, 5), ("Box Jump", 24, 1)],
        "log": [(date(2026, 12, 26), "Squat", 300, 1, "test"), (date(2026, 11, 1), "1-Board Press", 190, 3, "")],
        "bodyweight": {1: 180, 13: 185},
        "bodyfat": {1: (date(2026, 10, 6), 18.5, "InBody", 180)}}


def test_sheet_order(tmp_path):
    wb = load_workbook(build_workbook(tmp_path / "p.xlsx", DATA))
    names = wb.sheetnames
    assert names[0] == "Start Here"
    assert names[1:54] == [f"Week {w:02d}" for w in range(0, 53)]
    assert names[54:] == ["Log", "PRs", "Maxes", "Body", "Progress", "Sets", "Lists"]
    assert wb["Sets"].sheet_state == wb["Lists"].sheet_state == "hidden"
    assert wb["Week 05"]["C3"].value is None and wb["Week 01"]["C3"].value == 180
    assert wb["Start Here"]["A2"].value.startswith("Yellow")


def _recalc(tmp_path):
    build_workbook(tmp_path / "p.xlsx", DATA)
    subprocess.run(["soffice", "--headless", "--convert-to",
                    "csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,false,false,false,-1",
                    "--outdir", str(tmp_path), str(tmp_path / "p.xlsx")], check=True, capture_output=True, timeout=300)

    def sheet(name):
        with open(tmp_path / f"p-{name}.csv", newline="", encoding="utf-8") as f:
            return list(csv.reader(f))
    return sheet


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_formulas_calculate(tmp_path):
    sheet = _recalc(tmp_path)
    for name in ["Start Here", "Week 00", "Week 13", "Week 52", "PRs", "Maxes", "Body", "Progress"]:
        text = "\n".join(",".join(r) for r in sheet(name))
        assert not any(err in text for err in ("#NAME", "#VALUE", "#REF", "Err:")), name

    maxes = {r[0]: r for r in sheet("Maxes")}
    assert maxes["Squat"][4:6] == ["291.7", "300"]           # 250x5 baseline, then a 300 single before cycle 2
    assert maxes["Box Squat"][4] == "262.5"                  # estimated: squat x 0.9
    assert maxes["2-Board Press"][4] == "233.3"              # its own logged 5RM
    prs = {r[0]: r for r in sheet("PRs")}
    assert prs["1-Board Press"][3:7] == ["190", "190", "190", "0"]  # 1RM..4RM
    assert prs["Box Jump"][3] == "24"

    week13 = sheet("Week 13")
    squat = next(r for r in week13 if r[2] == "Squat")
    assert squat[6:8] == ["300", "210"]                      # 70% of 300
    start = "\n".join(",".join(r) for r in sheet("Start Here"))
    assert "Intermediate" in start                           # 24 in box, 70 in tall
    body = sheet("Body")
    assert body[3][10] == "144.2"                            # lean mass from the intake (178 lb, 19%)


def test_every_catalog_exercise_has_a_pr_row(tmp_path):
    wb = load_workbook(build_workbook(tmp_path / "p.xlsx"))
    names = [c.value for c in wb["PRs"]["A"][1:len(CATALOG) + 1]]
    assert names == list(CATALOG)


def test_no_external_links_excel_would_reject(tmp_path):
    """Sheet-to-sheet links must be internal (location=...), never external URL relationships."""
    import zipfile

    path = build_workbook(tmp_path / "p.xlsx", DATA)
    with zipfile.ZipFile(path) as z:
        rels = [n for n in z.namelist() if n.endswith(".rels")]
        assert not any('TargetMode="External"' in z.read(n).decode() for n in rels)
    wb = load_workbook(path)
    links = [c.hyperlink for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.hyperlink]
    assert len(links) > 100 and all(h.location and not h.target for h in links)
