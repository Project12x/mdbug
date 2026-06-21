"""Parse emulator perf dumps into a normalized sample list.

A sample is a list[int] of length `count`. Two source formats are supported:
- GDB `x/<count>hu &symbol` output (blastem, emusplatter --gdb-server)
- emusplatter --dump-workram text output (one `frame=N v0 v1 ...` line per dump)
"""
import re

_INT = re.compile(r"-?\d+")
_GDB_LINE = re.compile(r"^\s*0x[0-9a-fA-F]+.*?:\s*(.+)$")
_WATCH_LINE = re.compile(r"^MDBUG_WATCH (\S+) (-?\d+)$")


def parse_gdb_dump(text, count, width=None):
    """Flatten all GDB memory-dump line values, then chunk into samples of `count`.

    Robust to interleaved `Continuing.`/breakpoint lines: only lines shaped like
    `0xADDR ... : <ints>` contribute values. `width` is accepted for signature
    symmetry (GDB prints decimals already).
    """
    vals = []
    for line in text.splitlines():
        m = _GDB_LINE.match(line)
        if not m:
            continue
        for tok in m.group(1).split():
            if _INT.fullmatch(tok):
                vals.append(int(tok))
    n = len(vals) // count
    return [vals[i * count:(i + 1) * count] for i in range(n)]


def parse_watch(text):
    """Extract `MDBUG_WATCH <name> <int>` trace lines into per-name series.

    Returns `dict[name -> list[int]]`. The k-th occurrence of a given name is
    interval k, so each series tracks one global's value across intervals. These
    lines are not shaped like `0xADDR ... : <ints>`, so `parse_gdb_dump` ignores
    them and perf parsing is unaffected.
    """
    series = {}
    for line in text.splitlines():
        m = _WATCH_LINE.match(line)
        if not m:
            continue
        series.setdefault(m.group(1), []).append(int(m.group(2)))
    return series


def parse_export(text, count):
    """One sample per non-blank line; a leading `frame=N` token is ignored.

    Lines with fewer than `count` numeric values are skipped (partial writes).
    """
    samples = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        nums = [int(t) for t in line.split()
                if not t.startswith("frame=") and _INT.fullmatch(t)]
        if len(nums) >= count:
            samples.append(nums[:count])
    return samples
