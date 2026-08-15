"""Postgres row-level security for every deal-scoped table.

The application already injects the deal filter (esg.db.scope), but that only
protects traffic going through the ORM. These policies put the same predicate
in the database, so a Core query, an ad-hoc psql session, or a future service
that forgets the convention is still contained. Defence in depth: either layer
alone would do the job, and neither is trusted to.

Contract for callers: set the two session variables per transaction.

    SET LOCAL esg.deal_ids = 'D001,D002';   -- granted deals, comma separated
    SET LOCAL esg.all_deals = 'off';        -- 'on' only for audited admin use

A connection that sets neither sees nothing, which is the intended failure mode.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

from esg.db.models import DEAL_SCOPED_TABLES

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_PREDICATE = """
    current_setting('esg.all_deals', true) = 'on'
    OR deal_id = ANY (
        string_to_array(coalesce(current_setting('esg.deal_ids', true), ''), ',')
    )
"""


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite dev databases rely on the session-layer guard alone.

    for table in DEAL_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_deal_isolation ON {table}
            USING ({_PREDICATE})
            WITH CHECK ({_PREDICATE})
            """
        )

    # The audit log is append-only at the database level, not merely by
    # convention: revoke the verbs that would let history be rewritten.
    op.execute("REVOKE UPDATE, DELETE ON audit_event FROM PUBLIC")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION esg_audit_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_event is append-only (attempted %)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_no_rewrite
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION esg_audit_immutable()
        """
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_rewrite ON audit_event")
    op.execute("DROP FUNCTION IF EXISTS esg_audit_immutable()")
    for table in DEAL_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_deal_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
