import time
from datetime import datetime, timezone
from app import core, billing
from conftest import login


def test_30_day_period_matches_custom_and_can_switch_back(client):
    login(client)
    with core.db() as c:
        owner = c.execute(
            "SELECT id FROM users WHERE email='a@example.com'"
        ).fetchone()[0]
    tid = core.create_task(owner, "Usage regression", mode="work")
    today = int(time.time()) // 86400 * 86400
    for age in (0, 5, 10, 29, 30, 60):
        rid = billing.reserve(owner, tid, 0.001, "search")
        billing.settle(rid, 0.001)
        with core.db() as c:
            c.execute(
                "UPDATE usage_operations SET created=%s WHERE id=%s",
                (today - age * 86400 + 1, rid),
            )
    values = {}
    for days in (30, 7, 30, 90, 30):
        r = client.get(f"/api/usage?days={days}&limit=25&_refresh=fixture")
        assert r.status_code == 200, r.text
        assert r.json()["total"] == {7: 2, 30: 4, 90: 6}[days]
        values[days] = r.json()
    start = datetime.fromtimestamp(today - 29 * 86400, timezone.utc).strftime(
        "%Y-%m-%d"
    )
    end = datetime.fromtimestamp(today, timezone.utc).strftime("%Y-%m-%d")
    custom = client.get(f"/api/usage?days=30&start_date={start}&end_date={end}").json()
    assert (
        custom["totals"] == values[30]["totals"]
        and custom["daily"] == values[30]["daily"]
    )
    assert client.get("/api/usage/export.csv?days=30").status_code == 200
