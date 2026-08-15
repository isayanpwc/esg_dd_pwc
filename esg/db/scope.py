"""
Deal isolation, enforced in the session rather than at call sites.

The rule this module exists to make unbreakable: **a query against
deal-confidential data cannot run unless an authenticated principal is bound
to the current context, and it can only see the deals that principal has been
granted.** Forgetting a filter in a view or an agent is no longer possible,
because the filter is injected by a session event, not written by the caller.

Layers, outermost first:

1. bind_principal() puts an immutable Principal in a ContextVar.
2. A do_orm_execute hook injects `deal_id IN (...)` into every ORM SELECT that
   touches a DealScoped entity, and refuses outright when no principal is bound.
3. A before_flush hook rejects writes to deals the principal cannot edit.
4. On Postgres, row-level security policies apply the same predicate in the
   database, so a raw psql session or a Core query is still contained
   (migrations/versions/0002_row_level_security.py).

Platform administrators do not get implicit sight of every deal. An admin who
needs cross-deal reach must construct the principal explicitly through
all_deals_principal(), which is itself an audited action.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy import event, orm
from sqlalchemy.orm import Session, with_loader_criteria

from esg.db.models import DEAL_SCOPED_TABLES, DealScoped

_WRITE_LEVELS = {"Owner", "Editor"}
_current = ContextVar("esg_principal", default=None)


class ScopeViolation(PermissionError):
    """Raised when data is touched outside the caller's granted deals."""


class NoPrincipalBound(PermissionError):
    """Raised when deal-scoped data is queried with no authenticated caller."""


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str
    deal_permissions: dict = field(default_factory=dict)  # deal_id -> permission_level
    all_deals: bool = False

    @property
    def deal_ids(self):
        return frozenset(self.deal_permissions)

    def can_read(self, deal_id):
        return self.all_deals or deal_id in self.deal_permissions

    def can_write(self, deal_id):
        if self.all_deals:
            return True
        return self.deal_permissions.get(deal_id) in _WRITE_LEVELS


def current_principal():
    return _current.get()


def require_principal():
    principal = _current.get()
    if principal is None:
        raise NoPrincipalBound(
            "Deal-scoped data was accessed with no principal bound. "
            "Wrap the call in esg.db.scope.bind_principal(...)."
        )
    return principal


@contextmanager
def bind_principal(principal):
    token = _current.set(principal)
    try:
        yield principal
    finally:
        _current.reset(token)


@contextmanager
def no_principal():
    """Explicitly clear the principal — used by tests and by the login path,
    which must read the user table before any principal exists."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)


def load_principal(session, user_id, username, role):
    """Build a Principal from the live ACL table.

    Read with the principal cleared, since the ACL lookup itself precedes the
    scope that it defines.
    """
    from esg.db.models import DealAccessControl

    with no_principal():
        rows = session.query(DealAccessControl).filter(
            DealAccessControl.user_id == user_id,
            DealAccessControl.revoked_date.is_(None),
        ).all()
    return Principal(
        user_id=user_id,
        username=username,
        role=role,
        deal_permissions={r.deal_id: r.permission_level for r in rows},
    )


def all_deals_principal(admin_principal, reason):
    """Escalate an Admin to cross-deal visibility. Audited by the caller.

    Kept deliberately awkward: it takes a reason, and it refuses for anyone
    who is not an Admin, so breadth of access is never an accident.
    """
    if admin_principal.role != "Admin":
        raise ScopeViolation(
            f"Cross-deal access requires role Admin, not {admin_principal.role!r}"
        )
    if not reason or not reason.strip():
        raise ScopeViolation("Cross-deal access requires a stated reason")
    return Principal(
        user_id=admin_principal.user_id,
        username=admin_principal.username,
        role=admin_principal.role,
        deal_permissions=dict(admin_principal.deal_permissions),
        all_deals=True,
    )


def _mapped_deal_scope(state):
    """Deal-scoped entities the ORM can see in this statement."""
    return [m.class_ for m in state.all_mappers if _is_deal_scoped(m.class_)]


def _scoped_tables_in(statement):
    """Deal-scoped *tables* anywhere in the statement, including inside
    subqueries.

    Read-only traversal on purpose: the cloning visitors cannot copy the
    loader-criteria options this module itself attaches, and a detector must
    never mutate what it inspects.
    """
    found, seen = set(), set()

    def walk(element):
        if element is None or id(element) in seen:
            return
        seen.add(id(element))
        if getattr(element, "__visit_name__", "") == "table":
            name = getattr(element, "name", None)
            if name in DEAL_SCOPED_TABLES:
                found.add(name)
        try:
            children = element.get_children()
        except Exception:
            return
        for child in children:
            walk(child)

    walk(statement)
    return found


def _is_deal_scoped(target):
    try:
        return isinstance(target, type) and issubclass(target, DealScoped)
    except TypeError:
        return False


def install(session_factory):
    """Attach the enforcement hooks to a sessionmaker (idempotent)."""
    if getattr(session_factory, "_esg_scope_installed", False):
        return session_factory

    @event.listens_for(session_factory, "do_orm_execute")
    def _inject_deal_filter(state):
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            # Column/relationship loads refine an object the caller already
            # holds, which only got past this hook by being in scope.
            return
        if state.execution_options.get("esg_skip_scope"):
            return

        mapped = _mapped_deal_scope(state)
        tables = _scoped_tables_in(state.statement)
        if not mapped and not tables:
            return

        # Requiring the principal before anything else means an aggregate we
        # cannot filter still cannot run anonymously.
        principal = require_principal()
        if principal.all_deals:
            return

        if not mapped:
            # Forms like Query.count() wrap the entity in a subquery, which
            # strips the mapper; loader criteria would silently not apply and
            # the query would return every deal's rows. Refuse instead, and
            # point at the form that is enforceable.
            raise ScopeViolation(
                "This query reaches deal-scoped tables "
                f"({', '.join(sorted(tables))}) in a form the deal filter cannot be "
                "applied to — typically Query.count() or "
                "select(func.count()).select_from(Entity), both of which hide the "
                "entity inside a subquery. Use esg.db.repository.count(...) or "
                "select(func.count(Entity.<pk>)) instead."
            )

        permitted = tuple(principal.deal_ids)
        state.statement = state.statement.options(
            with_loader_criteria(
                DealScoped,
                lambda cls: cls.deal_id.in_(permitted),
                include_aliases=True,
            )
        )

    @event.listens_for(session_factory, "before_flush")
    def _guard_writes(session, flush_context, instances):
        pending = [
            (obj, "insert") for obj in session.new if isinstance(obj, DealScoped)
        ] + [
            (obj, "update") for obj in session.dirty if isinstance(obj, DealScoped)
        ] + [
            (obj, "delete") for obj in session.deleted if isinstance(obj, DealScoped)
        ]
        if not pending:
            return

        principal = require_principal()
        for obj, verb in pending:
            deal_id = getattr(obj, "deal_id", None)
            if deal_id is None:
                raise ScopeViolation(
                    f"{type(obj).__name__} was flushed without a deal_id ({verb})"
                )
            if not principal.can_write(deal_id):
                raise ScopeViolation(
                    f"{principal.username!r} may not {verb} "
                    f"{type(obj).__name__} in deal {deal_id!r}"
                )

    session_factory._esg_scope_installed = True
    return session_factory
