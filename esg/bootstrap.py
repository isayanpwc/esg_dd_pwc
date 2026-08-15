"""
Startup initialisation for hosted deployments.

A container starts with an empty database and no accounts, which would leave
the app unusable — there is no self-service signup any more, by design. This
module brings a fresh instance up to a usable state exactly once, driven by
environment variables so nothing is hardcoded and no credential is committed.

It is deliberately conservative:

* Schema creation runs Alembic when available and falls back to metadata
  creation, and is safe to call on every start.
* The first Admin is created only while the user table is empty. After that the
  bootstrap variables are inert, so they cannot become a standing back door.
* Nothing is created at all unless ESG_BOOTSTRAP_ADMIN_EMAIL and
  ESG_BOOTSTRAP_ADMIN_PASSWORD are both set.
"""

import logging
import os

from sqlalchemy import inspect, select

from esg.db import engine as db_engine
from esg.db.models import UserAccount
from esg.db.scope import no_principal

log = logging.getLogger(__name__)

_done = False


def ephemeral_storage_warning():
    """True when data will not survive a restart.

    Hugging Face Spaces give a container filesystem that resets on rebuild or
    sleep. A SQLite database there is a demo, not a system of record, and the
    interface should say so rather than let someone load a real target's data
    into something that will silently vanish.
    """
    from esg.config import settings

    on_spaces = bool(os.getenv("SPACE_ID"))
    sqlite = settings().resolved_database_url().startswith("sqlite")
    return on_spaces and sqlite


def ensure_schema():
    engine = db_engine.engine()
    if inspect(engine).has_table("user_account"):
        return "already-present"
    try:
        from alembic import command
        from alembic.config import Config

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config = Config(os.path.join(base, "alembic.ini"))
        config.set_main_option("script_location", os.path.join(base, "esg/db/migrations"))
        command.upgrade(config, "head")
        return "migrated"
    except Exception as exc:  # noqa: BLE001 - fall back rather than fail to start
        log.warning("Alembic upgrade unavailable (%s); creating schema from metadata", exc)
        db_engine.create_all()
        return "created"


def ensure_first_admin():
    """Create the initial Admin from environment, if the table is empty."""
    email = os.getenv("ESG_BOOTSTRAP_ADMIN_EMAIL", "").strip()
    password = os.getenv("ESG_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    username = os.getenv("ESG_BOOTSTRAP_ADMIN_USERNAME", "admin").strip()

    if not email or not password:
        return "not-requested"

    from esg.security import provisioning

    with db_engine.session() as session:
        with no_principal():
            existing = session.execute(select(UserAccount)).first()
            if existing is not None:
                return "already-provisioned"
            try:
                provisioning.bootstrap_admin(session, email, username, password)
            except provisioning.ProvisioningError as exc:
                log.error("Bootstrap admin refused: %s", exc)
                return f"refused: {exc}"
    return "created"


def initialise():
    """Idempotent, safe to call from the top of the Streamlit script."""
    global _done
    if _done:
        return None
    schema = ensure_schema()
    admin = ensure_first_admin()
    _done = True
    result = {"schema": schema, "admin": admin,
              "ephemeral": ephemeral_storage_warning()}
    log.info("ESG bootstrap: %s", result)
    return result
