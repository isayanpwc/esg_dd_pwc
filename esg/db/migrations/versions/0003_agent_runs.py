"""Agent run and step tables, with row-level security.

Adds the orchestration audit trail. The RLS block mirrors 0002 rather than
importing its predicate, so the two revisions stay independently replayable.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TABLES = ("agent_run", "agent_step")

_PREDICATE = """
    current_setting('esg.all_deals', true) = 'on'
    OR deal_id = ANY (
        string_to_array(coalesce(current_setting('esg.deal_ids', true), ''), ',')
    )
"""


def upgrade():
    from esg.db.models import AgentRun, AgentStep, Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[
        AgentRun.__table__, AgentStep.__table__,
    ])

    if bind.dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_deal_isolation ON {table}
            USING ({_PREDICATE})
            WITH CHECK ({_PREDICATE})
            """
        )


def downgrade():
    from esg.db.models import AgentRun, AgentStep, Base

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_deal_isolation ON {table}")
    Base.metadata.drop_all(bind=bind, tables=[
        AgentStep.__table__, AgentRun.__table__,
    ])
