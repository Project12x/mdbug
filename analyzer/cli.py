"""mdbug analyzer entrypoint: samples + config + baseline -> report.md + exit code.

Invoked by the PowerShell orchestrator. The baseline path in config may contain
a `{backend}` token, resolved here against --backend. Paths in config are
relative to the config file's directory.
"""
import argparse
import json
import os

from analyzer.config import load_config
from analyzer.parse import parse_gdb_dump, parse_export, parse_watch
from analyzer.gate import aggregate, gate
from analyzer.report import render_report, render_compare


def _baseline_path(cfg, cfg_dir, backend):
    raw = cfg["gate"]["baseline"].replace("{backend}", backend)
    return raw if os.path.isabs(raw) else os.path.join(cfg_dir, raw)


def _snapshot_path(cfg_dir, name):
    return os.path.join(cfg_dir, "perf", "snap.%s.json" % name)


def _run_compare(args, cfg, cfg_dir):
    """Load two named snapshots and render their side-by-side delta table."""
    a_name, b_name = args.compare
    with open(_snapshot_path(cfg_dir, a_name), "r", encoding="utf-8") as f:
        a = json.load(f)
    with open(_snapshot_path(cfg_dir, b_name), "r", encoding="utf-8") as f:
        b = json.load(f)
    a_meta = {"name": a_name, "gitSha": a.get("gitSha", "?"), "backend": a.get("backend", "?")}
    b_meta = {"name": b_name, "gitSha": b.get("gitSha", "?"), "backend": b.get("backend", "?")}
    fields = cfg["perf"]["fields"]
    md = render_compare(a_meta, b_meta, a.get("fields", {}), b.get("fields", {}), fields)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print("mdbug: compare written to %s" % args.out)
    print("mdbug: compare %s vs %s" % (a_name, b_name))
    return 0


def run(argv):
    ap = argparse.ArgumentParser(prog="mdbug-analyze")
    ap.add_argument("--config", required=True)
    ap.add_argument("--backend", default=None)
    # Not required: --compare mode needs no live samples (validated below).
    ap.add_argument("--samples-file", default=None)
    ap.add_argument("--samples-format", choices=["gdb", "export"], default=None)
    ap.add_argument("--shots-dir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--save-snapshot", default=None, metavar="NAME")
    ap.add_argument("--compare", nargs=2, default=None, metavar=("A", "B"))
    ap.add_argument("--done-ok", default="1")  # "1"/"0"
    ap.add_argument("--git-sha", default="?")
    ap.add_argument("--date", default="?")
    ap.add_argument("--project", default="?")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    cfg_dir = os.path.dirname(os.path.abspath(args.config))

    if args.compare:
        return _run_compare(args, cfg, cfg_dir)
    if not args.samples_file or not args.samples_format:
        ap.error("--samples-file and --samples-format are required unless --compare is used")

    backend = args.backend or cfg["backends"].get("default", "blastem")
    fields = cfg["perf"]["fields"]
    count = cfg["perf"]["count"]

    with open(args.samples_file, "r", encoding="utf-8") as f:
        text = f.read()
    if args.samples_format == "gdb":
        samples = parse_gdb_dump(text, count, cfg["perf"].get("width"))
    else:
        samples = parse_export(text, count)
    skip = cfg["perf"].get("skipSamples", 0)
    if skip:
        samples = samples[skip:]
    if not samples:
        print("mdbug: no samples parsed from %s" % args.samples_file)
        return 1
    observed = aggregate(samples, fields)

    if args.save_snapshot:
        snap_path = _snapshot_path(cfg_dir, args.save_snapshot)
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        payload = {"capturedAt": args.date, "gitSha": args.git_sha,
                   "backend": backend, "fields": observed}
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print("mdbug: snapshot written to %s" % snap_path)

    baseline_path = _baseline_path(cfg, cfg_dir, backend)
    if args.update_baseline:
        payload = {"capturedAt": args.date, "gitSha": args.git_sha,
                   "backend": backend, "fields": observed}
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print("mdbug: baseline written to %s" % baseline_path)
        return 0

    baseline_fields = {}
    if os.path.exists(baseline_path):
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline_fields = json.load(f).get("fields", {})

    verdict = gate(observed, baseline_fields, cfg["gate"].get("ceilings", {}),
                   cfg["gate"].get("tolerance", {}), fields, done_ok=(args.done_ok == "1"),
                   validity=cfg["gate"].get("validity"))

    watch = None
    if cfg.get("watch"):
        series = parse_watch(text)
        if skip:
            series = {name: vals[skip:] for name, vals in series.items()}
        watch = series

    shots = []
    if args.shots_dir and os.path.isdir(args.shots_dir):
        for name in sorted(os.listdir(args.shots_dir)):
            if name.lower().endswith(".png"):
                shots.append({"name": os.path.splitext(name)[0],
                              "path": os.path.join(os.path.basename(args.shots_dir), name).replace("\\", "/")})

    meta = {"project": args.project, "gitSha": args.git_sha, "date": args.date, "backend": backend}
    md = render_report(meta, verdict, shots, raw=text.strip(), watch=watch)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print("mdbug: report written to %s" % args.out)
    if verdict.get("invalid"):
        status = "INVALID"
    elif verdict["passed"]:
        status = "PASS"
    else:
        status = "FAIL"
    print("mdbug: %s" % status)
    for reason in verdict["reasons"]:
        print("  - %s" % reason)
    return 0 if verdict["passed"] else 1


def main():
    import sys
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
