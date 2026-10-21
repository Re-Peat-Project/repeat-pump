"""Pure parts of the wizard's "Load moisture from the cloud" (checks, command line, provenance)."""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).parents[1] / "qgis_plugin" / "repeat_pump_qgis"
sys.path.insert(0, str(PLUGIN.parent))
from repeat_pump_qgis.wizard import cloudload as cl, i18n  # noqa: E402


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def test_windows_are_checked_and_returned_as_iso():
    p, f = cl.check_windows("2023-07-01", "2023-10-31", "2023-04-01", "2023-11-30")
    assert p == ("2023-07-01", "2023-10-31") and f == ("2023-04-01", "2023-11-30")


@pytest.mark.parametrize("args,msg", [
    (("2023-7-1", "2023-10-31", "2023-04-01", "2023-11-30"), "YYYY-MM-DD"),
    (("2023-02-30", "2023-10-31", "2023-04-01", "2023-11-30"), "not a real date"),
    (("2023-10-31", "2023-07-01", "2023-04-01", "2023-11-30"), "before it starts"),
    (("2023-07-01", "2023-12-31", "2023-04-01", "2023-11-30"), "must contain"),
    (("", "", "", ""), "YYYY-MM-DD"),
])
def test_bad_windows_say_what_is_wrong(args, msg):
    with pytest.raises(ValueError, match=msg):
        cl.check_windows(*args)


def test_command_line_for_open_and_earth_engine():
    b = cl.with_margin((100.0, 200.0, 300.0, 400.0), 50)
    assert b == (50.0, 150.0, 350.0, 450.0)
    a = cl.fetch_args("stac", b, "EPSG:32749", "o.tif", ("2023-07-01", "2023-10-31"), ("2023-04-01", "2023-11-30"), 80)
    assert a[:3] == ["fetch-moisture", "--source", "stac"] and a[a.index("--bounds") + 1:a.index("--bounds") + 5] == ["50.000", "150.000", "350.000", "450.000"]
    assert a[a.index("--max-cloud") + 1] == "80" and "--ee-project" not in a
    e = cl.fetch_args("ee", b, "EPSG:32749", "o.tif", ("2023-07-01", "2023-10-31"), ("2023-04-01", "2023-11-30"), 80, " my-proj ")
    assert e[e.index("--ee-project") + 1] == "my-proj" and "--max-cloud" not in e
    with pytest.raises(ValueError, match="project id"):
        cl.fetch_args("ee", b, "EPSG:32749", "o.tif", ("a", "b"), ("c", "d"))


def test_provenance_is_read_from_the_sidecar_only(tmp_path):
    tif = tmp_path / "m.tif"
    assert cl.read_provenance(str(tif)) is None
    (tmp_path / "m.tif.provenance.json").write_text(json.dumps({"product": "P", "higher_is_wetter": True, "scenes_total": 7, "valid_fraction": 0.5}))
    prov = cl.read_provenance(str(tif))
    assert prov["higher_is_wetter"] is True and "Scenes: 7" in cl.summary(prov) and "50%" in cl.summary(prov)
    (tmp_path / "m.tif.provenance.json").write_text("{broken")
    assert cl.read_provenance(str(tif)) is None
