# TRACE — md-profiler call-graph tracing (complements the PC-sampler)

`PROFILING.md` covers mdbug's own **statistical PC-sampler** (where the 68000 spends
time, function-level, headless + deterministic, *sees inlined code* via pyelftools
DWARF). This doc covers the other half: **[md-profiler](https://github.com/Tails8521/md-profiler)**,
a host-side **tracing** profiler that records an exact **call graph with durations**.

They are complementary — pick by question:

| Question | Tool |
|---|---|
| "What % of the frame is in each function (incl. inlined)?" | PC-sampler (`PROFILING.md`) — headless, deterministic, automatable in the gate |
| "What called what, and how long did each call take?" | md-profiler (this doc) — exact call graph, interactive recording |

Both render to **Perfetto** (`ui.perfetto.dev`), so they share one viewer.

> **License boundary.** md-profiler is MIT; it requires a **GPLv3 fork of BlastEm**
> that emits `.mdp` traces. Both are **host-side tools** — you *run* the emulator and
> feed its trace file to md-profiler. Neither is ever linked into or shipped with the
> engine, so the engine's non-GPL boundary is untouched (same rule as every emulator
> mdbug drives over a wire/file).

---

## Install (Windows: prebuilt, no compile)

Both ship prebuilt Windows binaries — no source build:

- **md-profiler.exe** — <https://github.com/Tails8521/md-profiler/releases>
- **modified BlastEm** (`blastem-mdp.zip`) — <https://github.com/Tails8521/blastem/releases/tag/1.0.0>

Drop them in a host tools dir (they are *not* committed to any game repo). On this
machine they live at `~/opt/md-profiler/bin/md-profiler.exe` and
`~/opt/blastem-mdprofiler/blastem.exe`. Other OSes compile from source (md-profiler
is Rust/Cargo; the BlastEm fork uses its normal Makefile).

## Symbols (SGDK)

SGDK builds already emit `symbol.txt` (mdbug uses the same file for the PC-sampler).
That *is* md-profiler's `-s` symbol file — nothing extra to generate.

## Record a trace

1. Launch the **modified** BlastEm on your ROM: `blastem.exe out/rom.bin`.
2. Press **`u`** to open BlastEm's debugger console.
3. Type `mdp out/trace.mdp` — this resumes the game and records.
4. When the scenario you care about is done, press **`u`** again and type `smdp` to stop.

> Recording is **interactive** by design (a human drives the `u`/`mdp`/`smdp` keys),
> so it suits hand-driven deep-dives, not the headless gate. For automation, use the
> PC-sampler (`mdbug.ps1 -Profile`), which needs no console interaction.

## Generate + view the JSON

```
md-profiler -s out/symbol.txt -i out/trace.mdp -o out/trace.json
```

Open `out/trace.json` in <https://ui.perfetto.dev/> (or `chrome://tracing`).

---

## Inlined C functions (the `-O3 -flto` blind spot)

md-profiler only follows explicit `JSR`/`BSR`. With SGDK optimization on, most hot
helpers are **inlined** and never appear as calls. Two ways to deal with it:

- **Just use the PC-sampler for inlined code** — it already attributes samples to
  inlined functions through DWARF (`analyzer/symbolize.py`). Often enough.
- **Annotate** the function with the `instrumentation/mdp_label.h` drop-in to make
  md-profiler trace it *without changing codegen*:
  ```c
  #include "mdp_label.h"            // gated behind DEBUG_MDP_LABELS (default OFF)
  s16 helper(s16 a) {
    FUNCTION_START("helper");
    ... ; FUNCTION_END("helper"); return r;   // FUNCTION_END before EVERY return
  }
  ```
  Build with `-DDEBUG_MDP_LABELS=1`, then put `helper` on its own line in an
  **interval file** and pass it to BlastEm before recording. (The macro emits
  `mdp_label_helper_start_<n>` labels with a per-instance suffix; md-profiler
  matches your bare `helper` against that prefix.)
  ```
  md-profiler -m intervals.txt -s out/symbol.txt -b out/breakpoints.txt
  ```
  In the BlastEm console: `mbp out/breakpoints.txt` then `mdp out/trace.mdp`, then
  ```
  md-profiler -m intervals.txt -s out/symbol.txt -i out/trace.mdp -o out/trace.json
  ```

## Manual intervals (time between two points)

The interval-file format also measures arbitrary entry→exit spans (e.g. a whole
frame), one per line: `ENTRY[;ENTRY...],EXIT[;EXIT...],NAME,CATEGORY`. Example:
```
V_Int,WaitForVint,FrameTime,Frame time
```
See md-profiler's README for the full grammar.
