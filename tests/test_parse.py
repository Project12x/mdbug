from analyzer.parse import parse_gdb_dump, parse_export, parse_watch

GDB_TWO_SAMPLES = """\
Continuing.
Breakpoint 1, dbg_perf_tick () at src/main.c:105
0xff8000 <g_perf>:\t1\t2\t3\t4\t5\t6\t7\t8
0xff8010 <g_perf+16>:\t9\t10
Continuing.
Breakpoint 1, dbg_perf_tick () at src/main.c:105
0xff8000 <g_perf>:\t11\t12\t13\t14\t15\t16\t17\t18
0xff8010 <g_perf+16>:\t19\t20
"""

def test_parse_gdb_dump_chunks_by_count():
    samples = parse_gdb_dump(GDB_TWO_SAMPLES, count=10)
    assert samples == [[1,2,3,4,5,6,7,8,9,10], [11,12,13,14,15,16,17,18,19,20]]

def test_parse_gdb_dump_ignores_non_dump_lines():
    samples = parse_gdb_dump("garbage\n0xabc <x>:\t1 2 3\nmore garbage\n", count=3)
    assert samples == [[1,2,3]]

def test_parse_gdb_dump_drops_incomplete_trailing_chunk():
    samples = parse_gdb_dump("0xff8000:\t1 2 3 4 5", count=3)
    assert samples == [[1,2,3]]

def test_parse_export_one_sample_per_line():
    text = "frame=0 1 2 3\nframe=16 4 5 6\n"
    assert parse_export(text, count=3) == [[1,2,3],[4,5,6]]

def test_parse_export_skips_blank_and_short_lines():
    text = "frame=0 1 2 3\n\nframe=16 4 5\n"  # second data line too short
    assert parse_export(text, count=3) == [[1,2,3]]

GDB_WITH_WATCH = """\
Continuing.
0xff8000 <g_perf>:\t1\t2\t3
MDBUG_WATCH cam_x 16
MDBUG_WATCH cam_y -4
Continuing.
0xff8000 <g_perf>:\t4\t5\t6
MDBUG_WATCH cam_x 32
MDBUG_WATCH cam_y -8
"""

def test_parse_watch_extracts_series_by_interval():
    series = parse_watch(GDB_WITH_WATCH)
    assert series == {"cam_x": [16, 32], "cam_y": [-4, -8]}

def test_parse_watch_ignores_perf_and_noise_lines():
    series = parse_watch(GDB_WITH_WATCH)
    # perf values (1,2,3,...) must not leak into any watch series
    assert all(v not in (1, 2, 3, 4, 5, 6) for vals in series.values() for v in vals)

def test_parse_gdb_dump_ignores_watch_lines():
    # the critical invariant: watch lines must NOT fold into perf samples
    samples = parse_gdb_dump(GDB_WITH_WATCH, count=3)
    assert samples == [[1, 2, 3], [4, 5, 6]]

def test_parse_watch_empty_when_no_watch_lines():
    assert parse_watch("0xff8000:\t1 2 3\nContinuing.\n") == {}
