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

def test_skip_samples_drops_leading_intervals(tmp_path):
    import json
    cfg = {
        "backends": {"default": "blastem", "blastem": {}},
        "perf": {"symbol": "g", "count": 1, "width": "u16", "skipSamples": 1,
                 "fields": [{"index": 0, "name": "load", "aggregate": "max", "unit": "%", "gate": True}]},
        "gate": {"baseline": "b.json", "ceilings": {"load": 180}, "tolerance": {"default": 0}},
    }
    cp = tmp_path / "c.json"; cp.write_text(json.dumps(cfg))
    dump = tmp_path / "d.txt"; dump.write_text("frame=0 217\nframe=16 40\n")  # 217 would fail, but it's skipped
    rc = run(["--config", str(cp), "--backend", "blastem", "--samples-file", str(dump),
              "--samples-format", "export", "--out", str(tmp_path / "r.md")])
    assert rc == 0

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

def _cfg_with_validity(tmp_path):
    cfg = {
        "backends": {"default": "blastem", "blastem": {}},
        "perf": {"symbol": "g_perf", "count": 2, "width": "u16",
                 "fields": [{"index": 0, "name": "load", "aggregate": "max", "unit": "%", "gate": True},
                            {"index": 1, "name": "scroll_max", "aggregate": "max", "unit": "scanlines", "gate": True}]},
        "gate": {"baseline": "baseline.blastem.json", "ceilings": {"load": 180},
                 "tolerance": {"default": 0}, "validity": {"requireNonzero": ["scroll_max"]}},
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg))
    return p

def test_run_invalid_when_required_field_zero(tmp_path):
    cfg = _cfg_with_validity(tmp_path)
    (tmp_path / "baseline.blastem.json").write_text(json.dumps({"fields": {"load": 135, "scroll_max": 119}}))
    dump = tmp_path / "dump.txt"
    dump.write_text("frame=0 100 0\n")  # scroll_max == 0 -> INVALID
    out = tmp_path / "report.md"
    rc = run(["--config", str(cfg), "--backend", "blastem", "--samples-file", str(dump),
              "--samples-format", "export", "--out", str(out)])
    assert rc == 1  # invalid keeps a nonzero exit
    assert "Result: INVALID" in out.read_text()

def test_save_snapshot_writes_perf_dir(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "baseline.blastem.json").write_text(json.dumps({"fields": {"load": 135, "ovr": 1}}))
    dump = tmp_path / "dump.txt"
    dump.write_text("frame=0 130 0\n")  # within baseline+ceiling -> PASS
    rc = run(["--config", str(cfg), "--backend", "blastem", "--samples-file", str(dump),
              "--samples-format", "export", "--save-snapshot", "before", "--git-sha", "abc1234"])
    assert rc == 0
    snap = json.loads((tmp_path / "perf" / "snap.before.json").read_text())
    assert snap["fields"] == {"load": 130, "ovr": 0}
    assert snap["gitSha"] == "abc1234"

def test_compare_mode_renders_delta_table(tmp_path):
    cfg = _cfg(tmp_path)
    perf = tmp_path / "perf"
    perf.mkdir()
    (perf / "snap.A.json").write_text(json.dumps({"gitSha": "aaa", "backend": "blastem",
                                                  "fields": {"load": 130, "ovr": 0}}))
    (perf / "snap.B.json").write_text(json.dumps({"gitSha": "bbb", "backend": "blastem",
                                                  "fields": {"load": 135, "ovr": 1}}))
    out = tmp_path / "cmp.md"
    rc = run(["--config", str(cfg), "--compare", "A", "B", "--out", str(out)])
    assert rc == 0
    md = out.read_text()
    assert "| load | 130 | 135 | +5 |" in md
    assert "| ovr | 0 | 1 | +1 |" in md

def test_compare_mode_needs_no_samples(tmp_path):
    # --samples-file/--samples-format omitted entirely in compare mode
    cfg = _cfg(tmp_path)
    perf = tmp_path / "perf"
    perf.mkdir()
    (perf / "snap.A.json").write_text(json.dumps({"fields": {"load": 130, "ovr": 0}}))
    (perf / "snap.B.json").write_text(json.dumps({"fields": {"load": 135, "ovr": 1}}))
    rc = run(["--config", str(cfg), "--compare", "A", "B"])
    assert rc == 0

def test_missing_samples_without_compare_errors(tmp_path):
    import pytest
    cfg = _cfg(tmp_path)
    with pytest.raises(SystemExit):
        run(["--config", str(cfg)])

def test_run_emits_trajectory_when_watch_configured(tmp_path):
    cfg = {
        "backends": {"default": "blastem", "blastem": {}},
        "perf": {"symbol": "g_perf", "count": 3, "width": "u16",
                 "fields": [{"index": 0, "name": "load", "aggregate": "max", "unit": "%", "gate": True}]},
        "gate": {"baseline": "b.json", "ceilings": {"load": 180}, "tolerance": {"default": 0}},
        "watch": [{"name": "cam_x", "symbol": "g_dbg_cam_x"}],
    }
    cp = tmp_path / "c.json"; cp.write_text(json.dumps(cfg))
    dump = tmp_path / "d.txt"
    dump.write_text(
        "0xff8000 <g_perf>:\t1\t2\t3\nMDBUG_WATCH cam_x 16\n"
        "0xff8000 <g_perf>:\t4\t5\t6\nMDBUG_WATCH cam_x 32\n")
    out = tmp_path / "r.md"
    rc = run(["--config", str(cp), "--samples-file", str(dump),
              "--samples-format", "gdb", "--out", str(out)])
    assert rc == 0
    md = out.read_text()
    assert "## Trajectory" in md
    assert "| sample | cam_x |" in md
    assert "| 0 | 16 |" in md and "| 1 | 32 |" in md


def test_profile_samples_dispatches_nm_path(tmp_path):
    # --profile-samples runs the profile sub-pass *before* the gate's --samples-file
    # check, on the always-available nm floor (no pyelftools/capstone, no --elf).
    sym = tmp_path / "symbol.txt"
    sym.write_text("00000200 T func_a\n00000210 T func_b\n")
    samples = tmp_path / "pc.txt"
    samples.write_text("0x200\n0x210\n0x214\n")  # func_a x1, func_b x2
    out = tmp_path / "profile.folded"
    cfg = {
        "backends": {"default": "blastem", "blastem": {}},
        "perf": {"symbol": "g", "count": 1, "width": "u16",
                 "fields": [{"index": 0, "name": "load", "aggregate": "max", "unit": "%", "gate": True}]},
        "gate": {"baseline": "b.json", "ceilings": {"load": 180}, "tolerance": {"default": 0}},
        "profile": {"symbols": str(sym), "format": "folded"},
    }
    cp = tmp_path / "c.json"; cp.write_text(json.dumps(cfg))
    # note: no --samples-file/--samples-format -> would error in the gate path; profile dispatch wins.
    rc = run(["--config", str(cp), "--profile-samples", str(samples), "--out", str(out)])
    assert rc == 0
    folded = out.read_text()
    assert "func_b 2" in folded and "func_a 1" in folded
