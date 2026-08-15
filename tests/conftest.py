"""Shared fixtures. Every test gets an isolated in-memory database and its own
encryption key, so nothing leaks between tests or into the dev database."""

import base64
import os

import pytest

# Environment must be set before esg.config is first imported.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ESG_DATA_KEYS", "test-key:" + base64.b64encode(b"0" * 32).decode())
os.environ.setdefault("ESG_ACTIVE_KEY_ID", "test-key")


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Fresh schema per test, on a file-backed SQLite database.

    A file rather than :memory: so multiple sessions in one test see the same
    data, which is what the isolation tests need.
    """
    from esg import config
    from esg.db import engine as engine_mod

    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("ESG_DATA_KEYS", "test-key:" + base64.b64encode(b"0" * 32).decode())
    monkeypatch.setenv("ESG_ACTIVE_KEY_ID", "test-key")
    monkeypatch.setenv("ESG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    monkeypatch.setenv("ESG_DOCUMENT_DIR", str(tmp_path / "docs"))
    config.reload_settings()
    engine_mod.reset_engine()
    engine_mod.create_all()

    yield engine_mod

    engine_mod.reset_engine()
    config.reload_settings()


@pytest.fixture
def session(db):
    s = db.session_factory()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def admin():
    from esg.db.scope import Principal

    return Principal("u-admin", "admin", "Admin", {}, all_deals=True)


@pytest.fixture
def deal_setup(session, admin):
    """Two deals, three users with differing access.

    analyst  -> Editor on D1 only
    viewer   -> ReadOnly on D1 only
    manager  -> Owner on D2 only
    """
    from esg.db.models import CompanyMaster, DealMaster
    from esg.db.scope import Principal, bind_principal

    with bind_principal(admin):
        session.add_all([
            CompanyMaster(company_id="C1", company_name="Target One", industry="IT",
                          country="India"),
            CompanyMaster(company_id="C2", company_name="Target Two", industry="IT",
                          country="Germany"),
            DealMaster(deal_id="D1", deal_name="Project Alpha", company_id="C1"),
            DealMaster(deal_id="D2", deal_name="Project Beta", company_id="C2"),
        ])
        session.commit()

    return {
        "analyst": Principal("u-analyst", "analyst", "Analyst", {"D1": "Editor"}),
        "viewer": Principal("u-viewer", "viewer", "Viewer", {"D1": "ReadOnly"}),
        "manager": Principal("u-manager", "manager", "Manager", {"D2": "Owner"}),
    }
