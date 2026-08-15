"""
Query helpers whose results are guaranteed to be deal-filtered.

Some SQLAlchemy idioms hide the entity inside a subquery, which strips the ORM
mapper the deal filter needs — Query.count() being the common one. Rather than
let those return unfiltered rows, esg.db.scope refuses them outright and
callers use the equivalents here, which keep the entity visible to the filter.
"""

from sqlalchemy import func, inspect, select


def _primary_key_column(entity):
    """The *instrumented* primary-key attribute, not the raw Column.

    This distinction is load-bearing: a raw Column carries no ORM mapper, so a
    statement built from one is invisible to the deal filter and would be
    rejected by esg.db.scope. The class attribute keeps the entity visible.
    """
    mapper = inspect(entity)
    column = mapper.primary_key[0]
    return mapper.get_property_by_column(column).class_attribute


def count(session, entity, *criteria):
    """Deal-filtered row count.

    Counts the primary key rather than `*` so the entity stays in the
    statement and the scope hook can attach its predicate.
    """
    stmt = select(func.count(_primary_key_column(entity)))
    if criteria:
        stmt = stmt.where(*criteria)
    return session.execute(stmt).scalar() or 0


def exists(session, entity, *criteria):
    stmt = select(_primary_key_column(entity)).limit(1)
    if criteria:
        stmt = stmt.where(*criteria)
    return session.execute(stmt).first() is not None


def fetch_all(session, entity, *criteria, order_by=None, limit=None):
    stmt = select(entity)
    if criteria:
        stmt = stmt.where(*criteria)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    if limit:
        stmt = stmt.limit(limit)
    return session.execute(stmt).scalars().all()


def fetch_one(session, entity, *criteria):
    rows = fetch_all(session, entity, *criteria, limit=1)
    return rows[0] if rows else None


def group_count(session, entity, group_column, *criteria):
    """{group value: count} — grouped counts, still deal-filtered."""
    stmt = select(group_column, func.count(_primary_key_column(entity)))
    if criteria:
        stmt = stmt.where(*criteria)
    stmt = stmt.group_by(group_column)
    return {key: total for key, total in session.execute(stmt).all()}


def to_dataframe(session, entity, *criteria, order_by=None):
    """Deal-filtered DataFrame, for the agents that work in pandas.

    This is the supported replacement for the old pd.read_csv(uploads/...)
    pattern: same shape of data, but scoped to the caller's deals.
    """
    import pandas as pd

    rows = fetch_all(session, entity, *criteria, order_by=order_by)
    columns = [c.key for c in inspect(entity).mapper.column_attrs]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([{c: getattr(r, c) for c in columns} for r in rows])
