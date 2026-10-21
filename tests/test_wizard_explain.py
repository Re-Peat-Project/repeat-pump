"""The segment explainer is pure Python: it must reproduce what stage 6 stored, for both scoring methods."""
import sys
from pathlib import Path

import numpy as np
import pytest

PLUGIN = Path(__file__).parents[1] / "qgis_plugin" / "repeat_pump_qgis"
sys.path.insert(0, str(PLUGIN.parent))
from repeat_pump_qgis.wizard import explain as ex, i18n  # noqa: E402

W = {"burn_freq": 0.4, "peat_depth": 0.3, "dryness": 0.2, "upstream_contrib": 0.1}


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def seg(**kw):
    a = dict(seg_id="C1_001", status_mcda=1, subkhg_id="A", burn_freq_n=2, burn_share_dom=0.8, peat_class="3,0 - 4,0 meter", peat_share_dom=1.0,
             moisture_ring_mean=0.31, flow_acc_max=12.5, burn_freq_norm=1.0, peat_depth_norm=0.5, dryness_norm=0.2, upstream_contrib_norm=0.4,
             need_score=0.4 + 0.15 + 0.04 + 0.04, need_rank=3, selected=True, feasible=True)
    a.update(kw)
    return a


def test_weighted_rows_add_up_to_the_stored_score():
    e = ex.explain(seg(), {"weights": W}, {"n_scored": 20, "lowest_selected": 0.5})
    assert e.method == "weighted" and e.scored and "Selected" in e.headline and "rank 3 of 20" in e.headline
    assert [round(r.adds, 3) for r in e.rows] == [0.4, 0.15, 0.04, 0.04]
    assert abs(sum(r.adds for r in e.rows) - 0.63) < 1e-9 and not e.notes
    assert "2 burn year(s)" in e.rows[0].value and "3,0 - 4,0 meter" in e.rows[1].value and "0.31" in e.rows[2].value and "12.5" in e.rows[3].value


def test_a_segment_below_the_cut_says_how_far():
    e = ex.explain(seg(selected=False, need_score=0.3, need_rank=15, burn_freq_norm=0.0), {"weights": W}, {"n_scored": 20, "lowest_selected": 0.5})
    assert "Not selected" in e.headline and "0.500" in e.headline and "0.300" in e.headline


def test_weights_that_do_not_match_the_stored_score_are_called_out():
    e = ex.explain(seg(), {"weights": {k: 0.25 for k in W}}, {"n_scored": 20, "lowest_selected": 0.5})
    assert any("do not match" in n or "may differ" in n for n in e.notes)


def test_unscored_segments_say_why():
    assert "too short" in ex.explain(seg(status_mcda=0, need_score=np.nan), {}).headline
    assert "outside the selected sub-KHGs" in ex.explain(seg(subkhg_id=None), {}).headline
    assert not ex.explain(seg(status_mcda=0), {}).scored and not ex.explain(seg(status_mcda=0), {}).rows


def test_klh_method_shows_classes_and_the_threshold():
    rep = {"scoring": {"method": "klh", "min_score": 10, "max_score": 12}}
    a = seg(klh_burn=3, klh_peat=3, klh_dryness=2, klh_flow=2, klh_score=10, need_score=10 / 12)
    e = ex.explain(a, rep, {})
    assert e.method == "klh" and [r.score for r in e.rows] == [3, 3, 2, 2] and e.total_text == "Total 10 of 12" and "reaches the minimum of 10" in e.headline
    e2 = ex.explain({**a, "klh_score": 8, "selected": False}, rep, {})
    assert "below the minimum of 10" in e2.headline


def test_concession_and_staleness_notes():
    e = ex.explain(seg(feasible=False, selected=False, concession_share=0.9), {"weights": W}, {"n_scored": 5, "lowest_selected": 0.5}, stale=True)
    assert any("inside a concession" in n and "90%" in n for n in e.notes) and any("out of date" in n for n in e.notes)
    f = ex.explain(seg(concession_flag=True, concession_share=0.7), {"weights": W}, {})
    assert any("Flagged" in n for n in f.notes)


def test_html_is_escaped_and_complete():
    e = ex.explain(seg(peat_class="<b>x</b>"), {"weights": W}, {"n_scored": 20, "lowest_selected": 0.5})
    h = ex.to_html(e)
    assert "&lt;b&gt;x&lt;/b&gt;" in h and "<b>x</b>" not in h and "C1_001" in h and h.count("<tr>") == 5


def test_stats_from_rows():
    rows = [dict(need_score=0.9, selected=True), dict(need_score=0.6, selected=True), dict(need_score=0.2, selected=False), dict(need_score=np.nan, selected=False)]
    assert ex.stats_from_rows(rows) == {"n_scored": 3, "n_selected": 2, "lowest_selected": 0.6}


def test_the_explanation_reproduces_every_segment_of_a_real_stage_6_run(world):
    """Both methods, on the engine's own output: the rows must add up to what stage 6 stored."""
    from repeat_pump.core import prioritise
    from tests.test_m5_prioritise import _upto6

    def run(mutate=None):
        ctx = _upto6(world, mutate)
        prioritise.run(ctx)
        return ctx.read_layer("canal_segments"), ctx.report

    segs, rep = run()
    rows = segs.drop(columns="geometry").to_dict("records")
    stats = ex.stats_from_rows(rows)
    for r in rows:
        e = ex.explain(r, rep, stats)
        if r["need_score"] == r["need_score"]:
            assert abs(sum(x.adds for x in e.rows) - r["need_score"]) < 1e-6, r["seg_id"]
            assert e.headline.startswith("Selected") == bool(r["selected"])
    cfg, _ = world
    segs, rep = run(lambda c: c["prioritise"].update(weights_mode="klh", klh_cpwi_breaks=[0.0, 1.0], klh_flow_breaks=[1.0, 2.0], klh_min_score=8, upstream_buffer_m=50))
    rows = segs.drop(columns="geometry").to_dict("records")
    for r in rows:
        e = ex.explain(r, {"scoring": rep["scoring"], "weights": {}}, ex.stats_from_rows(rows))
        if r["need_score"] == r["need_score"]:
            assert e.method == "klh" and sum(x.score for x in e.rows) == r["klh_score"] and e.headline.startswith("Selected") == bool(r["selected"]), r["seg_id"]
