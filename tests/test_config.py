import json
import pytest
from analyzer.config import load_config, resolve_symbol_address, ConfigError

def test_resolve_symbol_address_finds_name():
    sym = "00ff0000 B g_perf\n00ff8000 B g_other\n00000200 T main\n"
    assert resolve_symbol_address(sym, "g_perf") == 0xFF0000

def test_resolve_symbol_address_missing_raises():
    with pytest.raises(KeyError):
        resolve_symbol_address("00ff0000 B g_other\n", "g_perf")

def test_load_config_reads_json(tmp_path):
    cfg = {"backends": {"default": "blastem", "blastem": {}},
           "perf": {"symbol": "g_perf", "count": 21, "width": "u16", "fields": []},
           "gate": {"baseline": "b.json", "ceilings": {}, "tolerance": {}}}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg))
    loaded = load_config(str(p))
    assert loaded["perf"]["count"] == 21

def test_load_config_missing_required_key_raises(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"perf": {}}')
    with pytest.raises(ConfigError):
        load_config(str(p))
