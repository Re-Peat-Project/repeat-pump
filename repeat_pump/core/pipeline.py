"""Stage orchestration with checkpoints, review stops and resume (spec section 2, 5)."""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from . import hydro, io, network, optimise, profiles, prioritise, pumps, report, routing, segments, sekat, topology
from .config import Config
from .context import RunContext
from .requirements import OPTIONS_BY_STAGE, fingerprint, get_value, needs_by_stage

# (id, name, function, needs human review)
STAGES = [
    (1, "load_validate", io.run_stage1, False),
    (2, "topology", topology.run, True),
    (3, "hydro", hydro.run, False),
    (4, "segments", segments.run, False),
    (5, "profiles", profiles.run, False),
    (6, "prioritise", prioritise.run, True),
    (7, "sekat", sekat.run, False),
    (8, "network", network.run, False),
    (9, "routing", routing.run, True),
    (10, "pumps", pumps.run, False),
    (11, "report", report.run, False),
    (12, "optimise", optimise.run, False),   # optional: records "skipped" unless optimise.enabled
]


def warning_stage(w: str) -> int:
    """Stage a warning belongs to: ``Stage N: ...`` messages to N; input-validation and ACCURACY warnings to stage 1."""
    m = re.match(r"Stage (\d+):", w)
    return int(m.group(1)) if m else 1


def reset_run(cfg: Config) -> list[str]:
    """Delete everything the engine wrote for this run (GeoPackage, work folder, state, report) and nothing else: the config,
    its preset and the input data stay. Returns what was removed. Refuses to touch anything outside the run's output folder."""
    import shutil

    from .config import resolve
    gpkg = resolve(cfg, cfg.run.output_gpkg)
    out = gpkg.parent.resolve()
    targets = [gpkg, gpkg.with_name(gpkg.name + "-wal"), gpkg.with_name(gpkg.name + "-shm"), out / "run_state.json",
               out / "run_report.md", out / "run_report.json", out / (gpkg.stem + "_work")]
    removed = []
    for t in targets:
        if not t.exists():
            continue
        if out not in t.resolve().parents:
            raise ValueError(f"refusing to delete {t}: outside the run folder {out}")
        shutil.rmtree(t) if t.is_dir() else t.unlink()
        removed.append(str(t))
    return removed


class ReviewRequired(Exception):
    """Raised (and caught by the CLI) when a REVIEW stage finished and awaits acceptance."""


def run_pipeline(cfg: Config, stop_after: Optional[int] = None, resume_from: Optional[int] = None,
                 accept: Optional[list[int]] = None, ctx: Optional[RunContext] = None) -> RunContext:
    ctx = ctx or RunContext(cfg)
    accepted = set(accept or []) | set(cfg.review.auto_accept)
    states = ctx.state.setdefault("stages", {})
    for sid, name, fn, review in STAGES:
        if resume_from is not None and sid < resume_from:
            continue
        key = str(sid)
        st = states.get(key, {}).get("status")
        if st == "done" and resume_from is None:
            continue
        if st == "awaiting_review" and sid in accepted and resume_from is None:
            states[key]["status"] = "done"; ctx.save_state()
            if stop_after == sid:
                break
            continue
        t0 = time.time()
        # Re-running a stage invalidates everything downstream of it: later stages must not be skipped as "done"
        # on the next run while their inputs have changed.
        for later in [k for k in states if int(k) > sid]:
            del states[later]
        # warnings raised by this stage or later ones belong to results that are about to be replaced
        ctx.warnings[:] = [w for w in ctx.warnings if warning_stage(w) < sid]
        proposed = [k for k in needs_by_stage(cfg)[sid] + OPTIONS_BY_STAGE.get(sid, []) if k in cfg.preset["keys"]]
        if proposed:                                     # one line per stage; the report lists the preset file and every value
            ctx.warn(f"Stage {sid}: {len(proposed)} proposed default(s), not team decisions: "
                     + ", ".join(f"{k} = {get_value(cfg, k)}" for k in proposed))
        states[key] = {"name": name, "status": "running"}
        ctx.save_state()
        (ctx.work / "logs").mkdir(exist_ok=True)
        fh = logging.FileHandler(ctx.work / "logs" / f"stage_{sid:02d}_{name}.log", mode="w", encoding="utf8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        ctx.log.addHandler(fh)
        ctx.log.setLevel(logging.INFO)
        ctx.log.info("Stage %s (%s) started", sid, name)
        ctx.current_stage = sid
        ctx.progress(0.0, name)
        try:
            outcome = fn(ctx)
            ctx.progress(1.0, name)
            ctx.log.info("Stage %s (%s) finished: %s", sid, name, ctx.report.get("counts", {}).get(str(sid), {}))
        except Exception as e:
            ctx.log.error("Stage %s failed: %s", sid, e)
            states[key] = {"name": name, "status": "failed", "error": str(e)}
            raise
        finally:
            ctx.log.removeHandler(fh); fh.close()
            ctx.save_state()
        states[key] = {"name": name, "seconds": round(time.time() - t0, 2),
                       "status": "skipped" if outcome == "skipped" else ("awaiting_review" if (review and sid not in accepted) else "done"),
                       "fingerprint": fingerprint(cfg, sid)}
        ctx.save_state()
        if states[key]["status"] == "awaiting_review":
            raise ReviewRequired(f"Stage {sid} ({name}) finished; inspect the QA layers in {ctx.gpkg} and re-run with --accept {sid}")
        if stop_after == sid:
            break
    return ctx
