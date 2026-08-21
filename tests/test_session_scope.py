"""The session/principal nesting contract.

esg.db.engine.session() commits as its own context manager exits. Anything that
binds a principal *inside* that context has already unbound it by the time the
flush runs, so deal-scoped writes fail with NoPrincipalBound. This was a real
defect in utils.auth.session_scope, found by running the app rather than by the
unit tests, which all bound the principal manually in the correct order.
"""

import pytest

from esg.db import engine as db_engine
from esg.db import repository
from esg.db.models import EsgMetricData
from esg.db.scope import NoPrincipalBound, Principal, bind_principal


@pytest.fixture
def owner(db, session, admin):
    from esg.db.models import CompanyMaster, DealMaster

    with bind_principal(admin):
        session.add_all([
            CompanyMaster(company_id="C1", company_name="Target"),
            DealMaster(deal_id="D1", deal_name="Project", company_id="C1"),
        ])
        session.commit()
    return Principal("u1", "analyst", "Analyst", {"D1": "Owner"})


def _metric(record_id="R1"):
    return EsgMetricData(
        record_id=record_id, deal_id="D1", company_id="C1",
        metric_code="ENV_SCOPE1", reporting_year=2024, value=1.0,
    )


def test_principal_must_outlive_the_commit(db, owner):
    """The wrong nesting order — the bug, pinned so it cannot come back."""
    with pytest.raises(NoPrincipalBound):
        with db_engine.session() as session:
            with bind_principal(owner):
                session.add(_metric("R-wrong"))
            # commit happens here, after the principal is unbound


def test_correct_nesting_commits_successfully(db, owner):
    with bind_principal(owner):
        with db_engine.session() as session:
            session.add(_metric("R-right"))

    with bind_principal(owner):
        with db_engine.session() as session:
            assert repository.count(session, EsgMetricData) == 1


def test_auth_session_scope_can_write(db, owner, monkeypatch):
    """utils.auth.session_scope is what every view uses, so a write through it
    has to reach the database."""
    import utils.auth as auth

    fake_state = {"esg_principal": owner, "logged_in": True}
    monkeypatch.setattr(auth.st, "session_state", fake_state, raising=False)

    with auth.session_scope() as session:
        session.add(_metric("R-view"))

    with bind_principal(owner):
        with db_engine.session() as session:
            rows = repository.fetch_all(session, EsgMetricData)
    assert [r.record_id for r in rows] == ["R-view"]


def test_session_scope_refuses_when_not_signed_in(db, monkeypatch):
    import utils.auth as auth

    monkeypatch.setattr(auth.st, "session_state", {}, raising=False)
    with pytest.raises(PermissionError, match="Not signed in"):
        with auth.session_scope():
            pass
