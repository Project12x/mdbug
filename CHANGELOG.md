# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- `median` and `p90` aggregate modes for perf fields (`analyzer/gate.py`):
  nearest-rank, integer-clean, robust to the few idle/load windows. Lets a
  project report and judge the typical and near-worst frame, not just the max.
  Schema `aggregate` enum and `tests/test_gate.py` updated. First consumer:
  jazzmd `scroll_median` / `scroll_p90`.
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
