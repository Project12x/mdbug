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
