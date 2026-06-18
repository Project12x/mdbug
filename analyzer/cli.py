"""mdbug analyzer entrypoint: samples + config + baseline -> report.md + exit code.

Invoked by the PowerShell orchestrator. The baseline path in config may contain
a `{backend}` token, resolved here against --backend. Paths in config are
relative to the config file's directory.
"""
import argparse
import json
import os

from analyzer.config import load_config
from analyzer.parse import parse_gdb_dump, parse_export
from analyzer.gate import aggregate, gate
from analyzer.report import render_report


def _baseline_path(cfg, cfg_dir, backend):
    raw = cfg["gate"]["baseline"].replace("{backend}", backend)
    return raw if os.path.isabs(raw) else os.path.join(cfg_dir, raw)


def run(argv):
    ap = argparse.ArgumentParser(prog="mdbug-analyze")
    ap.add_argument("--config", required=True)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--samples-file", required=True)
    ap.add_argument("--samples-format", choices=["gdb", "export"], required=True)
    ap.add_argument("--shots-dir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--done-ok", default="1")  # "1"/"0"
    ap.add_argument("--git-sha", default="?")
    ap.add_argument("--date", default="?")
    ap.add_argument("--project", default="?")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    cfg_dir = os.path.dirname(os.path.abspath(args.config))
    backend = args.backend or cfg["backends"].get("default", "blastem")
    fields = cfg["perf"]["fields"]
    count = cfg["perf"]["count"]

    with open(args.samples_file, "r", encoding="utf-8") as f:
        text = f.read()
    if args.samples_format == "gdb":
        samples = parse_gdb_dump(text, count, cfg["perf"].get("width"))
    else:
        samples = parse_export(text, count)
    if not samples:
        print("mdbug: no samples parsed from %s" % args.samples_file)
        return 1
    observed = aggregate(samples, fields)

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
                   cfg["gate"].get("tolerance", {}), fields, done_ok=(args.done_ok == "1"))

    shots = []
    if args.shots_dir and os.path.isdir(args.shots_dir):
        for name in sorted(os.listdir(args.shots_dir)):
            if name.lower().endswith(".png"):
                shots.append({"name": os.path.splitext(name)[0],
                              "path": os.path.join(os.path.basename(args.shots_dir), name).replace("\\", "/")})

    meta = {"project": args.project, "gitSha": args.git_sha, "date": args.date, "backend": backend}
    md = render_report(meta, verdict, shots, raw=text.strip())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print("mdbug: report written to %s" % args.out)
    print("mdbug: %s" % ("PASS" if verdict["passed"] else "FAIL"))
    for reason in verdict["reasons"]:
        print("  - %s" % reason)
    return 0 if verdict["passed"] else 1


def main():
    import sys
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
