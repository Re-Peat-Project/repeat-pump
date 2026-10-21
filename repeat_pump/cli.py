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


def _fetch_moisture(a, parser) -> int:
    from .core.cloudfetch import FetchError
    try:
        if a.ee_authenticate:
            from .core import ee_fetch
            ee_fetch.authenticate()
            print("Earth Engine sign-in finished")
            return 0
        missing = [n for n, v in (("--bounds", a.bounds), ("--crs", a.crs), ("--out", a.out), ("--primary", a.primary), ("--fallback", a.fallback)) if not v]
        if missing:
            parser.error("required: " + ", ".join(missing))     # the date windows have no defaults on purpose: they belong to the site and year
        if a.source == "ee":
            if not a.ee_project:
                parser.error("--ee-project is required with --source ee")
            from .core import ee_fetch
            prov = ee_fetch.fetch_cpwi(a.bounds, a.crs, a.out, tuple(a.primary), tuple(a.fallback), a.ee_project)
        else:
            from .core import cloudfetch
            prov = cloudfetch.fetch_s2_wetness(a.bounds, a.crs, a.out, tuple(a.primary), tuple(a.fallback), a.max_cloud, a.memory_gb)
        print(f"wrote {a.out}: {prov['product']}, {prov['valid_fraction']:.0%} of pixels valid")
        return 0
    except FetchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


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
    f = sub.add_parser("fetch-moisture", help="build a moisture raster from cloud imagery (open Sentinel-2 wetness index, or CPWI v2 via Earth Engine)")
    f.add_argument("--source", choices=["stac", "ee"], default="stac", help="stac: open Sentinel-2, no login; ee: exact CPWI v2 through Earth Engine")
    f.add_argument("--bounds", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"), help="area in --crs units (metres)")
    f.add_argument("--crs")
    f.add_argument("--out", help="output GeoTIFF")
    f.add_argument("--primary", nargs=2, metavar=("START", "END"), help="primary date window, YYYY-MM-DD")
    f.add_argument("--fallback", nargs=2, metavar=("START", "END"), help="wider window that fills the gaps of the primary one")
    f.add_argument("--max-cloud", type=float, help="scene cloud cover limit in %% (default 80, as in the legacy script)")
    f.add_argument("--memory-gb", type=float, default=4.0)
    f.add_argument("--ee-project", help="Earth Engine Cloud project id (--source ee)")
    f.add_argument("--ee-authenticate", action="store_true", help="one-time Earth Engine sign-in, then exit")
    a = ap.parse_args(argv)
    if a.cmd == "fetch-moisture":
        return _fetch_moisture(a, f)
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
