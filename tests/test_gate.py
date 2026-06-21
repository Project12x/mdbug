from analyzer.gate import aggregate, gate

FIELDS = [
    {"index": 0, "name": "load", "aggregate": "max",  "unit": "%",      "gate": True},
    {"index": 1, "name": "ovr",  "aggregate": "max",  "unit": "frames", "gate": True},
    {"index": 2, "name": "fc",   "aggregate": "last", "unit": "frames", "gate": False},
]
SAMPLES = [[100, 0, 16], [135, 1, 32], [120, 0, 48]]

def test_aggregate_max_and_last():
    obs = aggregate(SAMPLES, FIELDS)
    assert obs == {"load": 135, "ovr": 1, "fc": 48}

def test_aggregate_sum():
    fields = [{"index": 0, "name": "s", "aggregate": "sum", "unit": "", "gate": True}]
    assert aggregate([[1],[2],[3]], fields) == {"s": 6}

def test_gate_passes_within_baseline_and_ceiling():
    obs = {"load": 135, "ovr": 1, "fc": 48}
    v = gate(obs, {"load": 135, "ovr": 1}, {"load": 180}, {"default": 0}, FIELDS, done_ok=True)
    assert v["passed"] is True
    assert any(r["name"] == "fc" and r["result"] == "info" for r in v["rows"])

def test_gate_fails_on_ceiling():
    obs = {"load": 200, "ovr": 0, "fc": 48}
    v = gate(obs, {"load": 135, "ovr": 0}, {"load": 180}, {"default": 0}, FIELDS, done_ok=True)
    assert v["passed"] is False
    assert any("ceiling" in r for r in v["reasons"])

def test_gate_fails_on_regression_past_tolerance():
    obs = {"load": 138, "ovr": 0, "fc": 48}
    v = gate(obs, {"load": 135, "ovr": 0}, {"load": 180}, {"default": 0, "load": 2}, FIELDS, done_ok=True)
    assert v["passed"] is False  # 138 > 135 + 2

def test_gate_passes_regression_within_tolerance():
    obs = {"load": 137, "ovr": 0, "fc": 48}
    v = gate(obs, {"load": 135, "ovr": 0}, {"load": 180}, {"default": 0, "load": 2}, FIELDS, done_ok=True)
    assert v["passed"] is True  # 137 <= 135 + 2

def test_gate_fails_when_scenario_incomplete():
    obs = {"load": 100, "ovr": 0, "fc": 48}
    v = gate(obs, {"load": 135, "ovr": 0}, {}, {"default": 0}, FIELDS, done_ok=False)
    assert v["passed"] is False
    assert any("did not complete" in r for r in v["reasons"])

def test_gate_passes_at_exact_ceiling():
    obs = {"load": 180, "ovr": 0, "fc": 48}
    # baseline above observed so the regression check passes; observed == ceiling isolates the ceiling boundary
    v = gate(obs, {"load": 190, "ovr": 0}, {"load": 180}, {"default": 0}, FIELDS, done_ok=True)
    assert v["passed"] is True   # at-ceiling is not over-ceiling

def test_aggregate_median_and_p90():
    fields = [
        {"index": 0, "name": "med", "aggregate": "median", "unit": "", "gate": False},
        {"index": 0, "name": "p90", "aggregate": "p90",    "unit": "", "gate": False},
    ]
    samples = [[v] for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]]
    # nearest-rank over n=10: p50 -> xs[4]=50, p90 -> xs[8]=90 (actual observed values)
    assert aggregate(samples, fields) == {"med": 50, "p90": 90}

def test_aggregate_median_robust_to_idle_outliers():
    # two low load/idle windows (4, 5) among crossings ~120: median stays in the
    # crossing cluster, proving median/p90 are not dragged down by idle frames.
    fields = [{"index": 0, "name": "med", "aggregate": "median", "unit": "", "gate": False}]
    samples = [[v] for v in [4, 5, 118, 119, 120, 121, 122]]
    assert aggregate(samples, fields)["med"] == 119  # 4th of 7 sorted

def test_aggregate_percentile_empty_is_zero():
    fields = [{"index": 0, "name": "p", "aggregate": "p90", "unit": "", "gate": False}]
    assert aggregate([], fields) == {"p": 0}

def test_aggregate_index_out_of_range_raises():
    import pytest
    fields = [{"index": 5, "name": "x", "aggregate": "max", "unit": "", "gate": True}]
    with pytest.raises(ValueError):
        aggregate([[1, 2]], fields)

def test_gate_invalid_when_required_field_is_zero():
    # scroll_max == 0 means the camera never moved -> no usable activity.
    fields = [{"index": 0, "name": "scroll_max", "aggregate": "max", "unit": "", "gate": True}]
    v = gate({"scroll_max": 0}, {}, {}, {"default": 0}, fields, done_ok=True,
             validity={"requireNonzero": ["scroll_max"]})
    assert v["invalid"] is True
    assert v["passed"] is False
    assert v["reasons"][0] == "scroll_max == 0 (no activity) -- gate INVALID"

def test_gate_invalid_when_required_field_missing():
    fields = [{"index": 0, "name": "load", "aggregate": "max", "unit": "", "gate": True}]
    v = gate({"load": 100}, {}, {}, {"default": 0}, fields, done_ok=True,
             validity={"requireNonzero": ["scroll_max"]})
    assert v["invalid"] is True
    assert v["passed"] is False

def test_gate_valid_when_required_field_nonzero():
    fields = [{"index": 0, "name": "scroll_max", "aggregate": "max", "unit": "", "gate": True}]
    v = gate({"scroll_max": 119}, {}, {}, {"default": 0}, fields, done_ok=True,
             validity={"requireNonzero": ["scroll_max"]})
    assert v["invalid"] is False
    assert v["passed"] is True

def test_gate_invalid_reasons_prepended_before_other_reasons():
    fields = [{"index": 0, "name": "scroll_max", "aggregate": "max", "unit": "", "gate": True}]
    # also incomplete -> the INVALID reason must come first
    v = gate({"scroll_max": 0}, {}, {}, {"default": 0}, fields, done_ok=False,
             validity={"requireNonzero": ["scroll_max"]})
    assert v["invalid"] is True
    assert v["reasons"][0].endswith("gate INVALID")
    assert any("did not complete" in r for r in v["reasons"])

def test_gate_invalid_key_defaults_false_without_validity():
    v = gate({"load": 135, "ovr": 1, "fc": 48}, {}, {}, {"default": 0}, FIELDS, done_ok=True)
    assert v["invalid"] is False
