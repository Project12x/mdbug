"""Profile reporters: render symbolized PC counts into interchange formats.

Pure stdlib (``json`` only) -- no optional dep, always available, so these work
on both the rich ELF path and the legacy ``symbol.txt`` nm path. Each reporter
consumes the symbolizer's ``ranked`` list (the exact ``[{name, count, pct}]``
shape ``profile.profile_samples`` emits: count descending, then address
ascending, ``(unknown)`` last) plus an optional inline ``stacks`` dict mapping a
``';'``-joined frame key (outermost..innermost) to a sample count.

When ``stacks`` is provided (DWARF inline frames recovered from the ELF) the
output carries the full call frame per sample; when it is ``None`` (nm path, or
a ``-g0``/stripped ELF) each ranked function degrades to a single flat frame.
Either way the documents are valid and directly consumable:

- :func:`render_folded`    -> Brendan-Gregg folded stacks (flamegraph.pl/inferno)
- :func:`render_speedscope`-> speedscope ``sampled`` file format
- :func:`render_perfetto`  -> Chrome Trace Event JSON (Perfetto UI / chrome://tracing)

All three guard ``total == 0`` and emit an empty-but-valid document. ``meta`` is
the same dict ``profile.py`` already passes (``route``/``total``/``gitSha``) and
is used only for labels.
"""
import json

_SCHEMA = "https://www.speedscope.app/file-format-schema.json"


def _stack_items(ranked, stacks):
    """Yield ``(frames, count)`` pairs, deterministically ordered.

    ``frames`` is a list outermost..innermost. With ``stacks`` provided each key
    is split on ``';'``; otherwise each ranked row becomes a single-frame stack.
    Sorted by count descending, then key ascending, matching the symbolizer's
    determinism so reporter output is stable across runs.
    """
    if stacks:
        items = sorted(stacks.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(key.split(";"), count) for key, count in items]
    # nm / no-DWARF path: each function is its own single-frame stack. ranked is
    # already count-desc/addr-asc; re-key by (count desc, name asc) so flat output
    # is byte-stable regardless of the addr tiebreak in ranked.
    rows = sorted(ranked, key=lambda r: (-r["count"], r["name"]))
    return [([r["name"]], r["count"]) for r in rows]


def render_folded(ranked, stacks=None, meta=None):
    """Render Brendan-Gregg folded stacks: ``frameA;frameB;...;leaf count``.

    One line per stack. When ``stacks`` is given its ``';'``-joined keys are used
    verbatim (already outermost..innermost). When ``stacks`` is ``None`` each
    ranked row emits a flat single-frame line ``name count``. Lines are sorted by
    count descending then key ascending for determinism. Trailing newline. Empty
    input yields just a trailing newline (a valid empty folded file).
    """
    lines = []
    for frames, count in _stack_items(ranked, stacks):
        lines.append("%s %d" % (";".join(frames), count))
    return "\n".join(lines) + "\n"


def render_speedscope(ranked, stacks=None, meta=None):
    """Render a speedscope ``sampled`` profile (``json.dumps``, ``indent=2``).

    Builds a deduped shared frame table and one ``samples[]`` entry per stack
    (frame indices outermost->innermost) with a matching ``weights[]`` count.
    With ``stacks=None`` each ranked row becomes a single-frame sample. The
    ``profiles[0]`` ``endValue`` is the total sample count; ``startValue`` 0.
    """
    meta = meta or {}
    total = sum(r["count"] for r in ranked)
    frame_index = {}
    frames_table = []
    samples = []
    weights = []

    def _frame_idx(name):
        idx = frame_index.get(name)
        if idx is None:
            idx = len(frames_table)
            frame_index[name] = idx
            frames_table.append({"name": name})
        return idx

    for frames, count in _stack_items(ranked, stacks):
        samples.append([_frame_idx(f) for f in frames])
        weights.append(count)

    doc = {
        "$schema": _SCHEMA,
        "shared": {"frames": frames_table},
        "profiles": [
            {
                "type": "sampled",
                "unit": "none",
                "name": meta.get("route", "profile"),
                "startValue": 0,
                "endValue": total,
                "samples": samples,
                "weights": weights,
            }
        ],
    }
    return json.dumps(doc, indent=2)


def render_perfetto(ranked, stacks=None, meta=None):
    """Render Chrome Trace Event JSON the Perfetto UI / chrome://tracing ingests.

    This is a *weight* profile synthesized as a trace, not a wall-clock trace:
    ``ts``/``dur`` are synthetic sample-weight units, not nanoseconds. Each stack
    becomes a horizontal band of nested ``'X'`` (complete) duration events -- one
    per inline frame, outermost spanning the whole leaf weight, inner frames
    nested at the same ``ts`` -- laid out left-to-right by cumulative weight. With
    ``stacks=None`` every function is one flat ``'X'`` event. Wrapped as
    ``{"traceEvents": [...], "displayTimeUnit": "ns"}``.
    """
    total = sum(r["count"] for r in ranked)
    events = []
    ts = 0
    for frames, count in _stack_items(ranked, stacks):
        pct = round(100.0 * count / total, 1) if total else 0.0
        for depth, name in enumerate(frames):
            events.append({
                "name": name,
                "ph": "X",
                "ts": ts,
                "dur": count,
                "pid": 1,
                "tid": 1,
                "args": {"pct": pct, "samples": count, "depth": depth},
            })
        ts += count
    doc = {"traceEvents": events, "displayTimeUnit": "ns"}
    return json.dumps(doc, indent=2)


# addr2line / chrome://tracing both call this format "chrome trace"; expose the
# alias the design names so call sites can use either spelling.
render_chrome_trace = render_perfetto


def render_disasm(rows, symbol_name, meta=None):
    """Render an annotated instruction listing for one symbol as markdown.

    ``rows`` is the :class:`analyzer.disasm.InsnRow` list from
    :func:`analyzer.disasm.disasm_symbol` (one per decoded instruction, address
    order, each carrying its PC-sample ``count``/``pct``). Emits a fenced markdown
    table ``| PC | Samples | % | Insn |`` with the hottest instruction(s) flagged
    (a ``<-`` marker on every row sharing the peak nonzero sample count), so the
    expensive instruction inside the function jumps out.

    ``meta`` is the same dict ``profile.py`` passes (``route``/``gitSha``), used
    only for the header label. An empty ``rows`` yields a valid header-only doc.
    """
    meta = meta or {}
    total = sum(r.count for r in rows)
    peak = max((r.count for r in rows), default=0)

    lines = ["# mdbug disasm - %s" % symbol_name, ""]
    lines.append("Samples in range: %d  -  route `%s`  -  commit `%s`" %
                 (total, meta.get("route", "?"), meta.get("gitSha", "?")))
    lines.append("")
    lines.append("| PC | Samples | % | Insn |")
    lines.append("|---|---:|---:|---|")
    for r in rows:
        hot = "  <-" if r.count and r.count == peak else ""
        lines.append("| 0x%06x | %d | %.1f | `%s`%s |" %
                     (r.pc, r.count, r.pct, r.text, hot))
    return "\n".join(lines) + "\n"
