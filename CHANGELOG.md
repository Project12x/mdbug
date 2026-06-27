# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed
- `mdbug.ps1` now reads the configured `perf.doneFlag` dump and passes
  `--done-ok 0/1` to the analyzer. A deterministic route that samples perf data
  but never sets its completion flag now fails as `scenario did not complete`
  instead of silently reporting a valid-looking gate.

### Added
- **Profiler toolchain — ELF/DWARF symbolization, instruction disasm, interchange
  artifacts, and a first-class `-Profile` pass.** Adopted three OPTIONAL, import-guarded
  libs (pinned in `requirements.txt`); the stdlib nm floor (`profile.py` over
  `symbol.txt`) still works with none installed.
  - `analyzer/symbolize.py` (**pyelftools**): reads `.symtab` for **true** `st_size`
    ranges (EM_68K-checked) and the DWARF line program + inline-subroutine tree —
    `pc -> file:line` and the **inline call frames** behind SGDK `-O3`/`-flto` synthetic
    names (`.isra`/`.constprop`/`.lto_priv`/`.part`). Honors `profile.py`'s exact ranked
    contract; falls back to the nm path on any error / missing ELF / absent lib.
  - `analyzer/reporters.py` (pure stdlib): **folded** (Brendan-Gregg), **speedscope**,
    and **Perfetto/chrome-trace** renderers + `render_disasm`; valid on both the ELF and
    nm paths (inline frames when DWARF is present).
  - `analyzer/disasm.py` (**capstone** `CS_ARCH_M68K`): disassembles a hot symbol's true
    range from ROM bytes and weights **each 68k instruction** by the PCs in it.
  - CLI wiring: `profile.py` gains `--elf`/`--rom`/`--symbolizer {auto,elf,nm}`/`--format
    {md,folded,speedscope,perfetto}`/`--disasm SYMBOL` (all optional-dep imports lazy in
    `main()`); `cli.py` gains a `--profile-samples` sub-pass dispatched ahead of the gate.
  - **`mdbug.ps1 -Profile`**: a first-class pass — gdb dump of `g_pc_samples`
    (`lib/gdb_pc_dump.ps1`) + ROM-range filter + symbolize/render + a `## PC profile`
    report section, driven by a new config `profile.*` block (`-DryRun` prints the gdb
    script + python command). Schema gains the optional `profile` object.
  - **Call-graph tracing** (md-profiler): `TRACE.md` documents the complementary MIT
    tracing profiler + its host-only GPLv3 BlastEm fork (run over a file, never linked);
    `instrumentation/mdp_label.h` is an optional, flag-gated (`DEBUG_MDP_LABELS`) drop-in
    for annotating inlined functions without changing codegen.
  - 41 new host tests (`test_symbolize.py`/`test_reporters.py`/`test_disasm.py` with
    `importorskip` + a synthetic-ELF fixture; a `test_cli.py` nm-path dispatch test).
- **PC-sampling profiler — docs + reusable drop-in instrumentation.** Documented the
  end-to-end profiler workflow in **`PROFILING.md`**: the per-scanline HInt sampler that reads
  the *interrupted* 68k PC from the hardware interrupt frame (an asm trampoline; a C interrupt
  handler can't recover it reliably), the gdb dump of the RAM ring, and `analyzer/profile.py`
  symbolization — with the determinism (host-independent, laptop-safe) and observer-effect
  caveats spelled out. Vendored the reusable, project-agnostic drop-in target code under
  **`instrumentation/`** (`pc_sample.{h,c}` + `pc_sample_hint.s`, flag-gated `DEBUG_PC_SAMPLE`,
  default OFF) + `instrumentation/README.md`. `README.md` + `ARCHITECTURE.md` now cover
  `analyzer/profile.py` (it was shipped in a prior commit but undocumented).
- `median` and `p90` aggregate modes for perf fields (`analyzer/gate.py`):
  nearest-rank, integer-clean, robust to the few idle/load windows. Lets a
  project report and judge the typical and near-worst frame, not just the max.
  Schema `aggregate` enum and `tests/test_gate.py` updated. First consumer:
  jazzmd `scroll_median` / `scroll_p90`.
- Jitter/periodicity aggregate modes for feel-axis pacing work:
  `range`, `stdev`, `mean_abs_delta`, and `periodicity` (peak positive
  autocorrelation, 0-1000 score). Jazz MD now reports vcounter and scroll
  jitter/periodicity fields, and `build.bat autoplay frame-samples` makes
  `g_perf` snapshot every frame for true per-frame pacing runs (pair it with a
  route-length `perf.samples` count).
- Validity guard (`gate.validity.requireNonzero`): a list of field names that
  must be nonzero for a run to be valid. A zero/missing required field yields a
  new INVALID verdict (distinct from FAIL: the run produced no usable activity),
  reported as `<field> == 0 (no activity) -- gate INVALID` and a nonzero exit.
  `gate()` gains a `validity` kwarg and returns `invalid` (default False);
  report/CLI render `INVALID`. Catches "camera never moved" perf runs.
- A/B snapshot compare. `--save-snapshot NAME` writes the observed fields to
  `<cfg_dir>/perf/snap.<NAME>.json` during a normal run. `--compare A B` loads
  two snapshots and renders a side-by-side `| Metric | A | B | Delta |` table
  (`render_compare`), writes it to `--out`, and exits 0 -- no live samples
  required in compare mode.
- Watch trace. Optional top-level `watch: [{ name, symbol, format? }]`. The GDB
  sampler emits `MDBUG_WATCH <name> <value>` per interval (ignored by perf
  parsing); `parse_watch` collects per-name series and the report appends a
  `## Trajectory` table (one row per interval, one column per watch). Lets a run
  trace globals like `cam_x`/`cam_y` over time alongside the perf gate.
- Headless robustness. `mdbug.ps1` resolves gdb via a clear fallback chain
  (`backends.<be>.gdb` -> `$env:GDK` -> `build.gdk` -> `C:\SDKs\SGDK` ->
  `C:\SDKS\SGDK` -> PATH `m68k-elf-gdb`/`gdb`), throwing one error naming every
  candidate when none is found instead of silently sampling nothing.
  `lib/blastem_screenshot.ps1` now warns and returns (instead of throwing) when
  no window handle is available, so headless runs still produce metrics without
  needing `-NoScreenshots`. Schema gains `watch` and `gate.validity`.

## [0.1.2] - 2026-06-18

### Fixed
- Orchestrator now normalizes `..` in resolved paths: `Resolve-RepoPath` and `Resolve-BuildPath` wrap `Join-Path` in `[System.IO.Path]::GetFullPath(...)`.
- Build command invoked as a single cmd arg string (`/c $command`) instead of two args, preventing command parsing failures.
- Build dir prepended to `$env:PATH` (restored in `finally`) so the build command is found on machines that exclude the current directory from exe search.
- `--project` arg reported to the analyzer now derives from the build dir leaf rather than the config dir leaf. (All surfaced by the first live consumer run.)

## [0.1.1] - 2026-06-18

### Fixed
- Build step now sets the child working directory explicitly via `Start-Process -WorkingDirectory` so `build.bat` is found regardless of the .NET process CWD.
- Analyzer `--config` path is resolved to an absolute path early in `mdbug.ps1`, so relative paths passed by the caller work when the analyzer runs from the mdbug directory.
- GDB sampler quotes space-containing paths in the argument string passed to `Start-Process`, fixing empty output when the ELF or GDB script path contains spaces.

### Added
- `perf.skipSamples` config option (integer, default 0) to drop leading boot/warm-up intervals before the perf gate runs.

## [0.1.0] - 2026-06-17

### Added
- Config-driven MD perf gate with selectable `blastem` and `emusplatter` backends.
- Python analyzer (`analyzer/`) with parse, aggregate, gate, and report modules — no runtime dependencies beyond the standard library.
- 22 pytest host tests covering all analyzer modules; no emulator required.
- Shared GDB sampler (`lib/gdb_sample.ps1`) used by both backends; emusplatter additionally supports a batch work-RAM export sampler (`--dump-workram`).
- Checkpoint screenshot capture: wall-clock-based for blastem, frame-exact for emusplatter.
- JSON config schema (`config.schema.json`) and annotated example config (`examples/example.config.json`).
- BlastEm auto-installer (`install_blastem.ps1`).
- MIT license.
- Standard project docs: `README.md`, `HOWTO.md`, `ARCHITECTURE.md`, `CHANGELOG.md`.
