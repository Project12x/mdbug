# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
