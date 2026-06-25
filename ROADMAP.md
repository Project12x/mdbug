# Roadmap - Best-in-Class Mega Drive Debugging

This document is the durable plan for growing `mdbug` from a perf gate and
profiler into a full Mega Drive debugging and profiling suite.

The north star:

> Deterministic scenarios in, hardware-timed facts out, with enough visual
> context that a developer can tell why a frame was slow, torn, flickery, or
> felt bad.

The tool must stay reusable by non-Jazz projects. Jazz MD can be the proving
ground, but core features should be config-driven, documented, and usable by any
ROM that implements the instrumentation contract.

## Design Principles

- Keep the existing harness. Extend the analyzer, config schema, reports, and
  backend adapters; do not replace them with a project-specific runner.
- Preserve the four-item ROM contract: perf block, sample trigger,
  deterministic workload, optional done flag.
- Add new ROM instrumentation as optional capabilities, not new mandatory
  requirements.
- Prefer deterministic scripted runs over manual observation whenever the
  metric can be automated.
- Make hardware constraints explicit: VBlank timing, active display writes,
  DMA budget, SAT/sprite limits, CRAM/VRAM state, and input latency.
- Do not lock the suite to one emulator. BlastEm can remain a strong default,
  but the architecture should treat every emulator or emulator fork as a
  capability provider.
- Every advanced report should degrade gracefully when a backend cannot expose a
  capability.
- Store raw artifacts next to summaries so later tools can re-analyze old runs.

## Capability Model

`mdbug` should grow toward explicit capability detection. A backend/scenario
should declare or discover whether it supports:

| Capability | Purpose |
|---|---|
| `perf-block` | Sample scalar metrics from work RAM. |
| `done-flag` | Detect scenario completion and hangs. |
| `watch-trace` | Track globals over time, such as camera/player position. |
| `frame-samples` | Capture one sample per rendered frame. |
| `pc-sampling` | Attribute time to 68k code addresses. |
| `screenshots` | Attach visual checkpoints and overlays. |
| `input-tape` | Drive deterministic real-input scenarios. |
| `input-capture` | Record human-played input into a reusable tape. |
| `memory-dump` | Inspect RAM/VRAM/CRAM/SAT state. |
| `vdp-trace` | Record scroll/register timing or active-display writes. |

Reports should list which capabilities were active so missing sections are
understood as unavailable, not silently skipped.

## Backend And Fork Strategy

`mdbug` should be emulator-agnostic at the orchestration and analyzer layers.
Backends are adapters that acquire data; they are not the identity of the tool.

Supported or candidate backend families can include:

- BlastEm, including local forks for stronger debug hooks.
- emusplatter or other headless/export-oriented forks.
- Mesen-family or other multi-system emulators when they expose suitable Mega
  Drive hooks.
- Purpose-built internal forks that add deterministic memory export, VDP
  traces, screenshot checkpoints, input capture, or profiling clocks.

Forks are acceptable when they buy durable capability. A fork should be treated
as a maintained tool dependency with:

- a clear upstream base/version
- a patch list or branch name
- documented custom hooks
- deterministic command-line behavior
- a small smoke test ROM or fixture
- a capability manifest consumed by `mdbug`

The analyzer should not care whether a sample came from BlastEm, Mesen, ares,
emusplatter, or a project fork. The backend should emit normalized artifacts:
samples, screenshots, memory dumps, traces, profile samples, and metadata.

Backend selection should become capability-driven:

```json
{
  "scenario": { "requires": ["frame-samples", "input-capture", "vdp-trace"] },
  "backends": { "default": "blastem", "preferredFor": { "vdp-trace": "custom-fork" } }
}
```

Acceptance:

- Reports include backend name, version, fork metadata, and active
  capabilities.
- Scenarios can require capabilities and fail early with a clear message when
  the selected backend cannot provide them.
- Adding a new emulator should mean writing an adapter and manifest, not
  changing analyzer logic.

## Milestone 0: Clean Tooling Boundary

Goal: make the current state easy to reason about before larger work.

Work:

- Keep `mdbug` core changes inside the `mdbug` repository.
- Keep project integration changes, such as Jazz MD build flags and field maps,
  in the consuming project.
- Add a short capabilities table to reports.
- Standardize run artifacts:
  `config.json`, `samples.txt`, `report.md`, screenshots, profile outputs,
  git SHA, backend metadata, and scenario metadata.

Acceptance:

- A report can be archived and understood later without knowing the command
  line that produced it.
- The core repository remains standalone and testable without Jazz MD.

## Milestone 1: Scripted And Trained Real Input

Goal: unlock feel-axis testing without giving up determinism, while allowing a
human to "train" a route by playing it naturally first.

Work:

- Define an input tape format:

  ```json
  {
    "version": 1,
    "port": 1,
    "frames": [
      { "frame": 0, "buttons": [] },
      { "frame": 12, "buttons": ["RIGHT"] },
      { "frame": 48, "buttons": ["RIGHT", "B"] }
    ]
  }
  ```

- Support either state-per-frame or sparse edge encoding.
- Prefer in-ROM tape playback so normal game input handling remains active.
- Add analyzer/report metadata for the tape name, hash, duration, and button
  edges.
- Add gameplay-trained capture:
  - a recorder build/mode that samples the real joypad state once per frame
    while the developer plays
  - a compact in-ROM ring buffer or SRAM/work-RAM export
  - a host-side converter that writes the canonical `mdbug` input tape
  - trim/normalize tooling to cut leading idle frames, end after a done flag,
    and compress repeated button states
  - replay verification that compares the captured route's player/camera watch
    trace against the replayed tape
- Later convenience importers can ingest emulator movie formats, but the native
  recorder should be the first reliable path.

Training workflow:

1. Start a recorder scenario and play the route normally.
2. Export the captured per-frame joypad states from SRAM, work RAM, or backend
   memory dump.
3. Convert the capture to a canonical tape with stable metadata: ROM hash,
   build config hash, backend, region, start state, frame count, and done flag.
4. Replay the tape through the real input path.
5. Compare replay watch traces against the capture. If they match, promote the
   tape to a reusable scenario artifact.

Acceptance:

- A `DEBUG_AUTOPLAY=0` ROM can run a deterministic scenario through the real
  input path.
- A developer can play a route once, export it as an input tape, and replay it
  deterministically in a later gate/profile run.
- The gate can fail when the tape does not complete or the done flag is absent.

## Milestone 2: Feel Metrics

Goal: measure what throughput gates miss.

Work:

- Input-to-pixel latency:
  - input edge frame
  - first player motion frame
  - first camera motion frame
  - optional first sprite-position change frame
- Frame pacing:
  - per-frame vcounter distribution
  - `range`, `stdev`, `mean_abs_delta`, and `periodicity`
  - histogram buckets for report readability
- Tear / active-display probe:
  - vcounter before and after sensitive VDP writes
  - verdict: VBlank, active display, or ambiguous
- CRAM color-0 bar automation:
  - screenshot capture for timing bars
  - color-band measurement
  - section table with scanline heights

Acceptance:

- A scripted run reports input latency, pacing steadiness, tear status, and
  color-bar section timings when instrumentation is present.
- Feel metrics are gateable through the same baseline/ceiling mechanism as
  throughput metrics.

## Milestone 3: Frame Timeline

Goal: explain bad frames instead of only naming bad metrics.

Build a normalized timeline model:

```text
frame
  input state and edges
  watched globals
  perf fields
  vcounter/section timing
  scroll/register-write timing
  screenshots/checkpoints
  optional PC samples
```

Work:

- Add a timeline artifact, likely JSON, derived from samples and watch traces.
- Select frames of interest:
  - max vcounter
  - max scroll section
  - highest adjacent jitter
  - first input-response frame
  - tear-risk frame
  - overrun frame
- Render a compact "interesting frames" table in the report.

Acceptance:

- The report can answer "why did this frame feel bad?" without manually reading
  raw dumps.

## Milestone 4: Hardware Inspectors

Goal: expose common Mega Drive hardware failure modes.

Work:

- SAT / sprite inspector:
  - sprite count
  - link chain sanity
  - hidden or dropped sprites
  - max sprites per scanline against H40/H32 limits
- Sprite-per-scanline heatmap:
  - overlay or table for rows near/above the limit
- VRAM tile occupancy map:
  - used/free tile ranges
  - sprite engine range
  - plane map ranges
  - collision with reserved/system tiles
- CRAM viewer/diff:
  - palette values
  - changed entries by frame/checkpoint
  - color-0 profiler markers
- DMA budget report:
  - estimated or instrumented bytes per frame
  - VBlank budget comparison
  - active-display DMA flag when observable
- VDP register trace:
  - scroll mode
  - H/V scroll values
  - plane size/base settings
  - writes near active display

Acceptance:

- A run can produce hardware-state artifacts alongside perf metrics.
- At least SAT scanline pressure, CRAM state, and DMA budget are reportable in a
  backend-independent way when the ROM exports the required data.

## Milestone 5: Profiling Upgrade

Goal: connect CPU profiles to specific frame problems.

Work:

- Scoped profiles:
  - whole run
  - scroll section
  - sprite section
  - physics/update section
  - frame window around a spike
- Instruction-weighted disassembly for hot symbols.
- Inline/DWARF enrichment when optional dependencies are present.
- Keep nm symbol-table fallback as the no-dependency floor.
- First-class exports:
  - markdown flame table
  - folded stacks
  - speedscope
  - Perfetto

Acceptance:

- A spike frame can link to a scoped profile explaining the likely code cause.
- The profiler remains useful without pyelftools/capstone, and richer when they
  are installed.

## Milestone 6: Regression History And CI

Goal: make drift visible across commits and branches.

Work:

- Store run history in JSONL or SQLite.
- Track metrics by scenario, backend, git SHA, branch, and config hash.
- Add trend reports for selected metrics.
- Add baseline-management commands:
  - update
  - compare
  - explain changed fields
  - list stale baselines
- CI mode:
  - deterministic exit codes
  - artifact upload layout
  - compact summary for checks
- Later: first-bad-commit helper for a selected metric and scenario.

Acceptance:

- A developer can see whether input latency, jitter, overrun, or DMA pressure
  drifted over the last N commits.

## Milestone 7: Adoption Polish

Goal: make `mdbug` useful outside its original project.

Work:

- Scenario templates:
  - scroll route
  - sprite stress
  - input latency
  - DMA pressure
  - palette/CRAM timing bars
- Example ROM or minimal integration harness.
- Better report layout with charts and small visual summaries.
- Backend setup checker.
- Backend feature matrix in documentation.
- Backend authoring guide for new emulator adapters.
- Fork maintenance guide for custom emulator builds and debug hooks.
- Document BlastEm refresh policy and emulator accuracy/debug tradeoffs.

Acceptance:

- A new Mega Drive project can adopt `mdbug` by implementing the contract and
  starting from an example config.

## Near-Term Sprint

The next practical sprint should be:

1. Land project-side `frame-samples` and pacing-field wiring in the consuming
   project.
2. Add native gameplay input capture that records a human-played route into a
   canonical tape.
3. Add deterministic input tape playback for a real-input route.
4. Add input-to-pixel latency fields.
5. Add scroll-write tear probe fields.
6. Add a small "Feel" section to the report.

This sprint turns `mdbug` from a throughput gate into a feel-aware debugging
tool. Later milestones then build on a stronger data model instead of inventing
special cases.

## Open Questions

- Which backend should be authoritative for each capability: timing, frame-exact
  screenshots, memory dumps, VDP traces, input capture, and profile clocks?
- Should timeline artifacts live as one JSON file per run, or as separate
  streams for perf, input, watch, screenshots, and profiles?
- How much SAT/VRAM/CRAM inspection should be emulator-driven versus exported by
  ROM instrumentation?
- Should input tapes be a generic `mdbug` format plus optional importers for
  emulator movie formats, and which metadata is required to prove a captured
  route replayed identically?
- What is the minimum artifact set for CI so reports stay useful without storing
  very large screenshots/profiles on every run?
