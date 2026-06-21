from analyzer.report import render_report, render_compare

META = {"project": "jazzmd", "gitSha": "abc1234", "date": "2026-06-17", "backend": "blastem"}
VERDICT = {
    "passed": False,
    "rows": [
        {"name": "load", "observed": 200, "baseline": 135, "delta": 65, "ceiling": 180, "result": "fail", "unit": "%"},
        {"name": "fc",   "observed": 48,  "baseline": None, "delta": None, "ceiling": None, "result": "info", "unit": "frames"},
    ],
    "reasons": ["load 200 exceeds ceiling 180"],
}

def test_report_has_verdict_and_table():
    md = render_report(META, VERDICT, shots=[{"name": "boot", "path": "shots/boot.png"}], raw="0xff8000: 1 2 3")
    assert "FAIL" in md
    assert "jazzmd" in md and "abc1234" in md
    assert "| load |" in md
    assert "180" in md  # ceiling shown
    assert "![boot](shots/boot.png)" in md
    assert "load 200 exceeds ceiling 180" in md

def test_report_pass_has_no_failure_section():
    v = {"passed": True, "rows": VERDICT["rows"][:1], "reasons": []}
    v["rows"][0] = dict(v["rows"][0], result="pass", observed=130)
    md = render_report(META, v, shots=[], raw="")
    assert "Result: PASS" in md
    assert "## Failures" not in md

def test_report_invalid_status_and_section():
    v = {"passed": False, "invalid": True, "rows": VERDICT["rows"][:1],
         "reasons": ["scroll_max == 0 (no activity) -- gate INVALID"]}
    v["rows"][0] = dict(v["rows"][0], result="info", observed=0)
    md = render_report(META, v, shots=[], raw="")
    assert "Result: INVALID" in md
    assert "## Invalid" in md
    assert "## Failures" not in md

def test_report_trajectory_table_aligns_by_index():
    v = {"passed": True, "invalid": False, "rows": [], "reasons": []}
    watch = {"cam_x": [16, 32, 48], "cam_y": [-4, -8]}  # cam_y short -> padded
    md = render_report(META, v, shots=[], raw="", watch=watch)
    assert "## Trajectory" in md
    assert "| sample | cam_x | cam_y |" in md
    assert "| 0 | 16 | -4 |" in md
    assert "| 2 | 48 | - |" in md  # short series padded with -

COMPARE_FIELDS = [
    {"index": 0, "name": "scroll_max", "aggregate": "max", "unit": "scanlines", "gate": True},
    {"index": 1, "name": "dma_max", "aggregate": "max", "unit": "bytes", "gate": True},
]

def test_render_compare_side_by_side_with_delta():
    a_meta = {"name": "before", "gitSha": "aaa", "backend": "blastem"}
    b_meta = {"name": "after", "gitSha": "bbb", "backend": "blastem"}
    a = {"scroll_max": 119, "dma_max": 7000}
    b = {"scroll_max": 121, "dma_max": 6800}
    md = render_compare(a_meta, b_meta, a, b, COMPARE_FIELDS)
    assert "| Metric | before | after | Delta |" in md
    assert "| scroll_max | 119 | 121 | +2 |" in md
    assert "| dma_max | 7000 | 6800 | -200 |" in md

def test_render_compare_missing_value_renders_dash():
    a_meta = {"name": "before"}
    b_meta = {"name": "after"}
    md = render_compare(a_meta, b_meta, {"scroll_max": 100}, {}, COMPARE_FIELDS)
    assert "| scroll_max | 100 | - | - |" in md
    assert "| dma_max | - | - | - |" in md
