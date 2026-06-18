# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
