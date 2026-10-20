import json

import pytest

from repeat_pump.core import pumps
from repeat_pump.core.config import Config, MissingParameters, load_config
from repeat_pump.core.pipeline import ReviewRequired, run_pipeline
from tests.fixtures.synthetic import write_cfg


def test_pump_power_hand_calculation():
    """Test 9: P = rho g Q H / eta, hand-calculated: 1000*9.81*0.3*2.5/0.6/1000 = 12.2625 kW."""
    assert abs(pumps.pump_power_kw(0.3, 2.5, 0.6) - 12.2625) / 12.2625 < 0.01


def test_single_station_route():
    levels = [2.0, 2.3, 2.6, 2.9]
    out = pumps.site_stations(levels, [0, 0, 0, 0], z_src=2.0, max_head=1.5, sekat=[False] * 4)
    assert len(out) == 1 and abs(out[0]["h_m"] - 0.9) < 1e-9
    assert abs(pumps.pump_power_kw(0.2, out[0]["h_m"], 0.6) - 1000 * 9.81 * 0.2 * 0.9 / 0.6 / 1000) < 1e-9


def test_stations_split_and_snap_to_sekat():
    levels = [0, 0.6, 1.2, 1.8, 2.4]
    out = pumps.site_stations(levels, [0] * 5, z_src=0.0, max_head=1.0, sekat=[False, True, False, False, False])
    assert [s["idx"] for s in out][:2] == [0, 1] and out[1]["snapped"]       # second station snapped to the sekat node
    assert all(s["h_m"] <= 1.0 + 1e-9 for s in out)


def test_manning_and_hazen_williams():
    assert pumps.manning_hf(100, 1.0, 0.035, 4.0, 2.0) > 0
    assert pumps.hazen_williams_hf(100, 0.1, 120, 0.3) > 0


def test_pipeline_review_stops_and_full_run(world, tmp_path):
    cfg, tmp = world
    cfg["pumping"]["allow_gate_addition"] = True
    path = write_cfg(tmp / "c.yaml", cfg)
    c = load_config(path)
    with pytest.raises(ReviewRequired):                  # Stage 2 awaits review
        run_pipeline(c)
    with pytest.raises(ReviewRequired):                  # resume after accepting 2: Stage 6 awaits review
        run_pipeline(c, accept=[2])
    with pytest.raises(ReviewRequired):                  # Stage 9 awaits review
        run_pipeline(c, accept=[2, 6])
    ctx = run_pipeline(c, accept=[2, 6, 9])
    rep = json.loads((ctx.out_dir / "run_report.json").read_text())
    assert (ctx.out_dir / "run_report.md").exists()
    st = ctx.read_layer("pump_stations")
    assert len(st) >= 1 and (st.units_needed >= 1).all()
    assert all(abs(p - 1000 * 9.81 * q * h / 0.6 / 1000) < 1e-6 for p, q, h in zip(st.p_kw, st.q_m3s, st.h_m))
    assert "pumping.specific_yield" in rep["null_parameters"]
    layers = ["canals_clean", "qa_topology_dangles", "qa_topology_gaps", "canal_segments", "canal_profiles", "sekat_existing_assessed",
              "sekat_proposed", "network_nodes", "network_edges", "pump_sources", "pump_targets", "pump_routes", "pump_stations",
              "gates_required", "qa_unreachable_targets", "qa_sensitivity"]
    assert all(ctx.has_layer(l) for l in layers)


def test_missing_pump_params_listed(world):
    from repeat_pump.core import hydro, io, network, prioritise, profiles, routing, segments, sekat, topology
    from tests.conftest import make_ctx
    cfg, _ = world
    cfg["pumping"]["allow_gate_addition"] = True
    cfg["pumping"]["pump_efficiency"] = None
    cfg["pumping"]["pump_capacity_m3s"] = None
    ctx = make_ctx(cfg)
    for f in (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run, prioritise.run, sekat.run, network.run, routing.run):
        f(ctx)
    with pytest.raises(MissingParameters) as e:
        pumps.run(ctx)
    assert "pumping.pump_efficiency" in str(e.value) and "pumping.pump_capacity_m3s" in str(e.value)
