from analyzer.report import render_report

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
