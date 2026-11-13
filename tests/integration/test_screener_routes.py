import pytest
from fastapi.testclient import TestClient

from tests.integration.test_screener_snapshot import env  # noqa: F401  (the fixture)
from tests.support.portal import open_app

pytestmark = pytest.mark.integration


@pytest.mark.usefixtures("env")
def test_the_endpoint_runs_presets_and_custom_screens_and_refuses_bad_ones(tmp_path, pg_url):
    api = TestClient(open_app(pg_url, tmp_path))
    meta = api.get("/api/screener/meta").json()
    assert len(meta["presets"]) >= 20 and any(f["key"] == "roce" for f in meta["fields"])
    r = api.post(
        "/api/screener/run",
        json={
            "conditions": [{"field": "price_vs_sma200", "op": "gt", "value": 0}],
            "sort": "price",
        },
    )
    assert (
        r.status_code == 200
        and [x["symbol"] for x in r.json()["rows"]][0] == "UPPER"
        and r.json()["total"] >= 1
        and r.json()["as_of"]
    )
    assert api.post("/api/screener/run", json={"preset": "oversold"}).status_code == 200
    assert api.post("/api/screener/run", json={"preset": "nope"}).status_code == 404
    assert (
        api.post(
            "/api/screener/run", json={"conditions": [{"field": "zzz", "op": "gt", "value": 1}]}
        ).status_code
        == 422
    )
