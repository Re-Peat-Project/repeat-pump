"""Command line: ``repeat-pump run --config khg.yaml [--stop-after S] [--resume-from S] [--accept S ...]``."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__
from .core.config import ConfigError, InputError, load_config
from .core.pipeline import ReviewRequired, run_pipeline
from .core.requirements import check


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="repeat-pump")
    ap.add_argument("--version", action="version", version=f"repeat-pump {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--stop-after", type=int)
    r.add_argument("--resume-from", type=int)
    r.add_argument("--accept", type=int, action="append", default=[])
    c = sub.add_parser("check", help="list stages, review flags and the null parameters each stage still needs (JSON on stdout)")
    c.add_argument("--config", required=True)
    x = sub.add_parser("reset", help="delete the GeoPackage, work folder, state and report of a run (not the config or the inputs)")
    x.add_argument("--config", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "reset":
        from .core.pipeline import reset_run
        try:
            for p in reset_run(load_config(a.config)):
                print(f"removed {p}")
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "check":
        try:
            print(json.dumps(check(load_config(a.config))))
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        run_pipeline(load_config(a.config), a.stop_after, a.resume_from, a.accept)
    except ReviewRequired as e:
        print(e)
        return 2
    except (ConfigError, InputError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
