"""Tests for the PC-sampling symbolizer (analyzer.profile).

The symbolizer is clock-agnostic: it consumes a flat list of sampled 68k
program-counter values (from either a BlastEm-patch histogram or a native-
debugger HInt log) plus the SGDK `symbol.txt`, and attributes each PC to the
enclosing function. Run from tools/mdbug:  python -m pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.profile import (
    parse_symbol_table,
    symbolize_pc,
    profile_samples,
    parse_pc_samples,
    render_profile_report,
    main,
)


SYMBOLS = """\
00000200 t _Entry_Point
00000020 a font_pal_default_data_size
00001000 T draw_stream_delta_tiles
00000060 A tiles_000_palettes_raw_size
00001500 t level_bg_b_attr_at
00002000 T build_bg_a_column_strip_cache
"""


def test_parse_symbol_table_keeps_only_code_symbols_sorted_by_address():
    table = parse_symbol_table(SYMBOLS)
    # Only t/T (text/code) symbols; data/absolute (a/A) dropped; sorted ascending.
    assert table == [
        (0x0200, "_Entry_Point"),
        (0x1000, "draw_stream_delta_tiles"),
        (0x1500, "level_bg_b_attr_at"),
        (0x2000, "build_bg_a_column_strip_cache"),
    ]


def test_symbolize_pc_maps_to_enclosing_function():
    table = parse_symbol_table(SYMBOLS)
    # PC inside draw_stream_delta_tiles' range [0x1000, 0x1500).
    assert symbolize_pc(table, 0x1200) == "draw_stream_delta_tiles"
    # Exact symbol address belongs to that symbol.
    assert symbolize_pc(table, 0x1500) == "level_bg_b_attr_at"
    # PC in the last (open-ended) symbol.
    assert symbolize_pc(table, 0x2010) == "build_bg_a_column_strip_cache"


def test_symbolize_pc_below_first_symbol_is_none():
    table = parse_symbol_table(SYMBOLS)
    assert symbolize_pc(table, 0x0100) is None


def test_profile_samples_ranks_by_count_with_percentages():
    pcs = [0x1100, 0x1200, 0x1550, 0x2000, 0x2010, 0x0100]
    ranked = profile_samples(SYMBOLS, pcs)
    # 6 samples: draw_stream x2, build_bg_a x2, level_bg_b x1, unknown x1.
    # Ranked by count desc, then address asc for determinism.
    assert ranked == [
        {"name": "draw_stream_delta_tiles", "count": 2, "pct": 33.3},
        {"name": "build_bg_a_column_strip_cache", "count": 2, "pct": 33.3},
        {"name": "level_bg_b_attr_at", "count": 1, "pct": 16.7},
        {"name": "(unknown)", "count": 1, "pct": 16.7},
    ]


# --- Input contract: the sample file both clocks (HInt log / BlastEm patch) emit.

def test_parse_pc_samples_one_pc_per_line_hex():
    # Path C (native-debugger HInt log): one sampled PC per line.
    assert parse_pc_samples("0x1200\n0x1550\n") == [0x1200, 0x1550]


def test_parse_pc_samples_histogram_lines_expand_to_counts():
    # Path B (BlastEm patch): "<count> <pc>" pre-aggregated histogram lines.
    assert parse_pc_samples("3 0x1000\n1 0x2000\n") == [
        0x1000, 0x1000, 0x1000, 0x2000,
    ]


def test_parse_pc_samples_ignores_comments_and_blank_lines():
    assert parse_pc_samples("# clock=hint route=autoplay\n\n0x10\n") == [0x10]


def test_render_profile_report_lists_functions_in_rank_order():
    ranked = profile_samples(SYMBOLS, [0x1100, 0x1200, 0x1550])
    md = render_profile_report(ranked, {"total": 3, "route": "autoplay"})
    assert "draw_stream_delta_tiles" in md
    assert "66.7" in md  # 2 of 3
    assert "autoplay" in md
    # Higher-ranked function appears before lower-ranked one.
    assert md.index("draw_stream_delta_tiles") < md.index("level_bg_b_attr_at")


def test_main_writes_report_from_symbol_and_sample_files():
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        sym = os.path.join(d, "symbol.txt")
        samp = os.path.join(d, "pc.txt")
        out = os.path.join(d, "profile.md")
        with open(sym, "w", encoding="utf-8") as f:
            f.write(SYMBOLS)
        with open(samp, "w", encoding="utf-8") as f:
            f.write("0x1100\n0x1200\n0x1550\n")

        rc = main(["--symbols", sym, "--samples", samp,
                   "--out", out, "--route", "autoplay"])

        assert rc == 0
        with open(out, "r", encoding="utf-8") as f:
            md = f.read()
    assert "draw_stream_delta_tiles" in md
    assert "autoplay" in md
