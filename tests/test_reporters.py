"""Tests for the profile reporters (analyzer.reporters).

Pure-stdlib renderers (folded / speedscope / perfetto-chrome-trace) that turn
the symbolizer's ``ranked`` counts -- and an optional inline ``stacks`` dict --
into interchange formats. These run unconditionally (no optional dep): the
reporters degrade to flat single-frame output when ``stacks`` is None, exactly
the nm-path shape. Run from tools/mdbug:  python -m pytest tests/
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.reporters import (
    render_folded,
    render_speedscope,
    render_perfetto,
    render_chrome_trace,
)

# The exact ranked shape profile.profile_samples emits: count desc, addr asc,
# (unknown) last. The reporters re-key flat output by (count desc, name asc).
RANKED = [
    {"name": "draw_stream_delta_tiles", "count": 3, "pct": 50.0},
    {"name": "build_bg_a_column_strip_cache", "count": 2, "pct": 33.3},
    {"name": "level_bg_b_attr_at", "count": 1, "pct": 16.7},
]

# Inline frames (outermost..innermost), addr2line -i style. draw_stream is hot
# and inlined two deep; build_bg_a is a single frame.
STACKS = {
    "frame_loop;draw_stream_delta_tiles;blit_row": 3,
    "frame_loop;build_bg_a_column_strip_cache": 2,
}

META = {"route": "autoplay", "total": 6, "gitSha": "abc1234"}


# --- folded -----------------------------------------------------------------

def test_folded_flat_path_one_line_per_function_sorted_by_count():
    out = render_folded(RANKED)
    assert out == (
        "draw_stream_delta_tiles 3\n"
        "build_bg_a_column_strip_cache 2\n"
        "level_bg_b_attr_at 1\n"
    )
    assert out.endswith("\n")


def test_folded_uses_inline_stack_keys_verbatim():
    out = render_folded(RANKED, STACKS, META)
    assert out == (
        "frame_loop;draw_stream_delta_tiles;blit_row 3\n"
        "frame_loop;build_bg_a_column_strip_cache 2\n"
    )


def test_folded_sorted_count_desc_then_key_asc():
    stacks = {"b_low": 1, "a_hi": 5, "c_mid": 5}
    out = render_folded([], stacks)
    # 5-weight ties broken by key ascending (a_hi before c_mid); 1-weight last.
    assert out == "a_hi 5\nc_mid 5\nb_low 1\n"


def test_folded_empty_is_just_trailing_newline():
    assert render_folded([]) == "\n"
    assert render_folded([], {}) == "\n"


# --- speedscope -------------------------------------------------------------

def test_speedscope_flat_path_shape_and_frame_table():
    doc = json.loads(render_speedscope(RANKED, None, META))
    assert doc["$schema"] == "https://www.speedscope.app/file-format-schema.json"
    assert doc["shared"]["frames"] == [
        {"name": "draw_stream_delta_tiles"},
        {"name": "build_bg_a_column_strip_cache"},
        {"name": "level_bg_b_attr_at"},
    ]
    prof = doc["profiles"][0]
    assert prof["type"] == "sampled"
    assert prof["unit"] == "none"
    assert prof["name"] == "autoplay"
    assert prof["startValue"] == 0
    assert prof["endValue"] == 6  # total samples
    # One single-frame sample per ranked row; weights line up with frame indices.
    assert prof["samples"] == [[0], [1], [2]]
    assert prof["weights"] == [3, 2, 1]


def test_speedscope_inline_dedupes_frames_and_maps_indices():
    doc = json.loads(render_speedscope(RANKED, STACKS, META))
    names = [f["name"] for f in doc["shared"]["frames"]]
    # frame_loop is shared across both stacks -> appears once, index 0.
    assert names == [
        "frame_loop",
        "draw_stream_delta_tiles",
        "blit_row",
        "build_bg_a_column_strip_cache",
    ]
    prof = doc["profiles"][0]
    # Outermost->innermost frame indices, in count-desc/key-asc stack order.
    assert prof["samples"] == [[0, 1, 2], [0, 3]]
    assert prof["weights"] == [3, 2]
    assert prof["endValue"] == 6


def test_speedscope_empty_is_valid_document():
    doc = json.loads(render_speedscope([], None, META))
    assert doc["shared"]["frames"] == []
    prof = doc["profiles"][0]
    assert prof["samples"] == [] and prof["weights"] == []
    assert prof["startValue"] == 0 and prof["endValue"] == 0


def test_speedscope_is_indented_json():
    text = render_speedscope(RANKED, None, META)
    assert "\n  " in text  # indent=2 pretty-print


# --- perfetto / chrome trace ------------------------------------------------

def test_perfetto_flat_one_complete_event_per_function():
    doc = json.loads(render_perfetto(RANKED, None, META))
    assert doc["displayTimeUnit"] == "ns"
    evs = doc["traceEvents"]
    assert [e["name"] for e in evs] == [
        "draw_stream_delta_tiles",
        "build_bg_a_column_strip_cache",
        "level_bg_b_attr_at",
    ]
    # All complete 'X' events; dur == sample weight; ts laid out cumulatively.
    assert all(e["ph"] == "X" for e in evs)
    assert [e["dur"] for e in evs] == [3, 2, 1]
    assert [e["ts"] for e in evs] == [0, 3, 5]
    assert all(e["pid"] == 1 and e["tid"] == 1 for e in evs)
    # pct = 100 * count / total (total = 6).
    assert evs[0]["args"]["pct"] == 50.0
    assert evs[2]["args"]["pct"] == round(100.0 / 6, 1)


def test_perfetto_inline_nests_frames_at_same_ts():
    doc = json.loads(render_perfetto(RANKED, STACKS, META))
    evs = doc["traceEvents"]
    # First stack: 3 nested frames, all ts=0, dur=3, depth 0..2.
    first = [e for e in evs if e["ts"] == 0]
    assert [e["name"] for e in first] == [
        "frame_loop", "draw_stream_delta_tiles", "blit_row",
    ]
    assert [e["args"]["depth"] for e in first] == [0, 1, 2]
    assert all(e["dur"] == 3 for e in first)
    # Second stack starts at ts == first leaf weight (3).
    second = [e for e in evs if e["ts"] == 3]
    assert [e["name"] for e in second] == [
        "frame_loop", "build_bg_a_column_strip_cache",
    ]
    assert all(e["dur"] == 2 for e in second)


def test_perfetto_empty_is_valid_document():
    doc = json.loads(render_perfetto([], None, META))
    assert doc["traceEvents"] == []
    assert doc["displayTimeUnit"] == "ns"


def test_render_chrome_trace_is_perfetto_alias():
    assert render_chrome_trace is render_perfetto
    a = render_chrome_trace(RANKED, STACKS, META)
    b = render_perfetto(RANKED, STACKS, META)
    assert a == b


# --- cross-cutting ----------------------------------------------------------

def test_all_reporters_accept_stacks_none_without_meta():
    # The nm path may pass neither stacks nor meta; must not raise.
    assert render_folded(RANKED) .endswith("\n")
    json.loads(render_speedscope(RANKED))
    json.loads(render_perfetto(RANKED))
