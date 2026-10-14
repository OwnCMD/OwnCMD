"""Community usage accounting; provider calls do not require prepaid balances."""

import time
import pytest
from app import core, billing, accounts


def account():
    owner = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (owner, owner + "@example.com", "unused", time.time()),
        )
    return owner, core.create_task(owner, "Build an application", mode="work")


def operation(rid):
    with core.db() as c:
        return dict(
            c.execute("SELECT * FROM usage_operations WHERE id=%s", (rid,)).fetchone()
        )


def test_no_wallet_and_no_markup():
    owner, task = account()
    rid = billing.reserve(owner, task, 50)
    billing.settle(rid, 0.125)
    billing.settle(rid, 0.125)
    row = operation(rid)
    assert row["cost_nano"] == row["charge_nano"] == 125000000
    report = billing.activity(owner)
    assert report["totals"]["charge"] == 0.125
    assert "wallet" not in report and "grants" not in report
    with core.db() as c:
        assert (
            c.execute("SELECT to_regclass('credit_transactions')").fetchone()[0] is None
        )


def test_duplicate_provider_id_and_pending_cost():
    owner, task = account()
    a = billing.reserve(owner, task, 0.1)
    b = billing.reserve(owner, task, 0.1)
    billing.settle(a, None, provider_id="generation-1")
    assert operation(a)["status"] == "pending"
    billing.record(b, provider_id="generation-1")
    billing.settle(a, 0.04)
    billing.settle(b, 0.04)
    assert billing.activity(owner)["totals"]["charge"] == 0.04


def test_owner_limit_still_enforced():
    owner, task = account()
    with core.db() as c:
        c.execute(
            "INSERT INTO account_settings(owner,body) VALUES(%s,%s)",
            (owner, '{"limits":{"daily_spend_usd":1}}'),
        )
    billing.reserve(owner, task, 0.8)
    with pytest.raises(billing.CreditError, match="Daily spending limit"):
        billing.reserve(owner, task, 0.3)


def test_runtime_is_free_by_default_but_records_seconds(monkeypatch):
    monkeypatch.delenv("ASTER_BROWSER_COST_PER_HOUR", raising=False)
    owner, task = account()
    billing.start_runtime("example", task, "browser")
    with core.db() as c:
        r = c.execute("SELECT * FROM runtime_meters").fetchone()
    billing.stop_runtime("example", now=r["started"] + 20)
    report = billing.activity(owner)
    assert report["totals"]["seconds"] == 20
    assert report["totals"]["charge"] == 0


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1e99"])
def test_invalid_cost_rejected(amount):
    owner, task = account()
    with pytest.raises(ValueError):
        billing.reserve(owner, task, amount)


def pending_estimate(owner):
    with core.db() as c:
        return billing.usd(
            c.execute(
                "SELECT coalesce(sum(hold_nano),0) FROM usage_operations WHERE owner=%s AND status IN ('reserved','pending')",
                (owner,),
            ).fetchone()[0]
        )


def test_title_cost_recorded_and_reconciliation_idempotent():
    owner, task = account()
    rid = billing.reserve(owner, task, 0.1, service="title")
    billing.settle(rid, 0.03)
    billing.reconcile_operation(rid, 0.04, "provider-invoice-1")
    billing.reconcile_operation(rid, 0.04, "provider-invoice-1")
    assert operation(rid)["cost_nano"] == operation(rid)["charge_nano"] == 40000000
    assert billing.activity(owner)["totals"]["charge"] == 0.04
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM usage_adjustments").fetchone()[0] == 1
