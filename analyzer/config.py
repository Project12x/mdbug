"""Load/validate a project config and resolve the perf block address."""
import json
import re

_SYM = re.compile(r"^([0-9a-fA-F]+)\s+\S+\s+(\S+)")
_REQUIRED = ("backends", "perf", "gate")


class ConfigError(Exception):
    pass


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for key in _REQUIRED:
        if key not in cfg:
            raise ConfigError("config missing required key: %s" % key)
    return cfg


def resolve_symbol_address(symbol_text, name):
    """Return the int address of `name` from SGDK symbol.txt (`<hex> <type> <name>`)."""
    for line in symbol_text.splitlines():
        m = _SYM.match(line)
        if m and m.group(2) == name:
            return int(m.group(1), 16)
    raise KeyError("symbol not found: %s" % name)
