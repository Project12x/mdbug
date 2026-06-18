import json
from analyzer.cli import run

def _cfg(tmp_path, baseline_name="baseline.blastem.json"):
    cfg = {
        "backends": {"default": "blastem", "blastem": {}},
        "perf": {"symbol": "g_perf", "count": 2, "width": "u16",
                 "fields": [{"index": 0, "name": "load", "aggregate": "max", "unit": "%", "gate": True},
                            {"index": 1, "name": "ovr", "aggregate": "max", "unit": "frames", "gate": True}]},
        "gate": {"baseline": baseline_name, "ceilings": {"load": 180}, "tolerance": {"default": 0}},
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg))
    return p

def test_run_pass_writes_report_and_returns_zero(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "baseline.blastem.json").write_text(json.dumps({"fields": {"load": 135, "ovr": 1}}))
    dump = tmp_path / "dump.txt"
    dump.write_text("frame=0 100 0\nframe=16 135 1\n")
    out = tmp_path / "report.md"
    rc = run(["--config", str(cfg), "--backend", "blastem", "--samples-file", str(dump),
              "--samples-format", "export", "--out", str(out), "--git-sha", "abc1234",
              "--date", "2026-06-17", "--project", "jazzmd"])
    assert rc == 0
    assert "Result: PASS" in out.read_text()

def test_run_fail_returns_one(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "baseline.blastem.json").write_text(json.dumps({"fields": {"load": 135, "ovr": 1}}))
    dump = tmp_path / "dump.txt"
    dump.write_text("frame=0 200 0\n")  # 200 > ceiling 180
    out = tmp_path / "report.md"
    rc = run(["--config", str(cfg), "--backend", "blastem", "--samples-file", str(dump),
              "--samples-format", "export", "--out", str(out)])
    assert rc == 1

def test_update_baseline_writes_file(tmp_path):
    cfg = _cfg(tmp_path)
    dump = tmp_path / "dump.txt"
    dump.write_text("frame=0 140 2\n")
    rc = run(["--config", str(cfg), "--backend", "blastem", "--samples-file", str(dump),
              "--samples-format", "export", "--update-baseline"])
    assert rc == 0
    saved = json.loads((tmp_path / "baseline.blastem.json").read_text())
    assert saved["fields"] == {"load": 140, "ovr": 2}
    assert saved["backend"] == "blastem"
