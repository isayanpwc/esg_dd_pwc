"""Baseline schema.

The baseline is created from the ORM metadata so revision 1 and the models
cannot drift. Every revision after this one is hand-written DDL.

Revision ID: 0001
Revises: None
"""

from alembic import op

from esg.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
