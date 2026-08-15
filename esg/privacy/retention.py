"""
Retention and erasure — for the platform's own personal data.

Easy to overlook: the tool holds personal data about its *users* (names, work
emails, login history) and, inside target documents, about the target's
employees. DPDP and GDPR therefore apply to the platform itself, not only to
the companies it assesses.

Two obligations pull in opposite directions and are resolved explicitly here:

* Erasure — a data subject may require their personal data to be deleted.
* Audit integrity — the audit trail must remain verifiable, and an engagement
  file must be retained for the professional retention period.

The resolution: personal data is *redacted* while the audit chain's structure
is preserved. Erasing a user's PII replaces the encrypted fields with a tombstone
and leaves the hash chain intact, so history stays verifiable without holding
the person's details. Audit rows are never deleted, since deleting one would
break verification for every row after it — the honest answer to "erase my audit
trail" is that the professional retention obligation overrides it, and that is
recorded rather than quietly ignored.
"""

import json
import uuid

from sqlalchemy import select

from esg import clock
from esg.config import settings
from esg.db.models import (
    AuditEvent, DocumentPage, ErasureRequest, EsgDocumentRegister, UserAccount,
)
from esg.db.scope import no_principal
from esg.security import audit, rbac

TOMBSTONE = "[erased]"


class RetentionError(RuntimeError):
    pass


def _days(count):
    from datetime import timedelta

    return timedelta(days=count)


def report(session):
    """What is currently past its retention window."""
    today = clock.today()
    cfg = settings()

    with no_principal():
        expired_documents = session.execute(
            select(EsgDocumentRegister).where(
                EsgDocumentRegister.retention_expires_at.is_not(None),
                EsgDocumentRegister.retention_expires_at < today,
            ).execution_options(esg_skip_scope=True)
        ).scalars().all()

        audit_cutoff = clock.now() - _days(cfg.retention_days_audit)
        expired_audit = session.execute(
            select(AuditEvent).where(AuditEvent.occurred_at < audit_cutoff)
            .execution_options(esg_skip_scope=True)
        ).scalars().all()

        inactive = session.execute(
            select(UserAccount).where(UserAccount.is_active.is_(False))
        ).scalars().all()

    return {
        "as_of": today.isoformat(),
        "documents_expired": len(expired_documents),
        "document_ids": [d.document_id for d in expired_documents][:100],
        "audit_expired": len(expired_audit),
        "audit_retention_days": cfg.retention_days_audit,
        "document_retention_days": cfg.retention_days_documents,
        "inactive_accounts": len(inactive),
        "note": (
            "Audit events past the window are reported but never deleted: removing "
            "one breaks hash-chain verification for every later event. Archive the "
            "chain instead."
        ),
    }


def purge_expired(session, actor_principal, dry_run=False):
    """Delete document content past its retention date.

    The register row is kept as a tombstone — that a document existed, and when
    it was purged, is itself part of the engagement record.
    """
    rbac.check(rbac.PURGE_DATA, principal=actor_principal)
    today = clock.today()

    with no_principal():
        expired = session.execute(
            select(EsgDocumentRegister).where(
                EsgDocumentRegister.retention_expires_at.is_not(None),
                EsgDocumentRegister.retention_expires_at < today,
            ).execution_options(esg_skip_scope=True)
        ).scalars().all()

    pages_removed = 0
    for document in expired:
        with no_principal():
            pages = session.execute(
                select(DocumentPage).where(
                    DocumentPage.document_id == document.document_id
                ).execution_options(esg_skip_scope=True)
            ).scalars().all()
        if dry_run:
            pages_removed += len(pages)
            continue
        for page in pages:
            session.delete(page)
            pages_removed += 1
        document.file_path = None
        document.processing_status = "Purged"
        document.processing_error = f"Content purged under retention policy on {today}"

    if not dry_run and expired:
        audit.record(
            session, actor_principal.username, "retention.purged",
            detail={"documents": len(expired), "pages": pages_removed},
        )
    return {"documents": len(expired), "pages": pages_removed, "dry_run": dry_run}


def erase_subject(session, email, actor_principal, basis="data subject request"):
    """Honour an erasure request for a platform user.

    PII is replaced with a tombstone; the account row and the audit chain
    survive. Returns a record of what was and was not erased, because a
    partially-honoured request must be disclosed to the subject.
    """
    rbac.check(rbac.PURGE_DATA, principal=actor_principal)

    from esg.security.provisioning import email_hash

    subject_hash = email_hash(email)
    with no_principal():
        accounts = session.execute(
            select(UserAccount).where(UserAccount.email_hash == subject_hash)
        ).scalars().all()

    if not accounts:
        raise RetentionError("No account matches that email address.")

    erased, retained = [], []
    for account in accounts:
        account.email = f"{TOMBSTONE}:{account.user_id}"
        account.full_name = TOMBSTONE
        account.password_hash = None
        account.idp_subject = None
        account.is_active = False
        account.deleted_at = clock.now()
        erased.append({"user_account": account.user_id,
                       "fields": ["email", "full_name", "password_hash", "idp_subject"]})

        with no_principal():
            events = session.execute(
                select(AuditEvent).where(AuditEvent.actor == account.username)
                .execution_options(esg_skip_scope=True)
            ).scalars().all()
        if events:
            retained.append({
                "audit_event": len(events),
                "reason": (
                    "Audit entries are retained under the professional retention "
                    "obligation and to keep the hash chain verifiable. The actor "
                    "username remains; no contact details are held in these rows."
                ),
            })

    request = ErasureRequest(
        request_id=uuid.uuid4().hex[:32],
        subject_email_hash=subject_hash,
        basis=basis,
        requested_by=actor_principal.username,
        status="Completed",
        completed_at=clock.now(),
        outcome_json=json.dumps({"erased": erased, "retained": retained}, default=str),
    )
    session.add(request)

    audit.record(
        session, actor_principal.username, "privacy.subject_erased",
        entity_type="erasure_request", entity_id=request.request_id,
        detail={"subject_hash": subject_hash[:12], "accounts": len(accounts),
                "audit_rows_retained": sum(r.get("audit_event", 0) for r in retained)},
    )
    session.flush()
    return {"request_id": request.request_id, "erased": erased, "retained": retained}


def subject_access(session, email, actor_principal):
    """Data-subject access request: everything held about one person."""
    rbac.check(rbac.MANAGE_USERS, principal=actor_principal)

    from esg.security.provisioning import email_hash

    subject_hash = email_hash(email)
    with no_principal():
        accounts = session.execute(
            select(UserAccount).where(UserAccount.email_hash == subject_hash)
        ).scalars().all()

    payload = []
    for account in accounts:
        with no_principal():
            events = session.execute(
                select(AuditEvent).where(AuditEvent.actor == account.username)
                .order_by(AuditEvent.seq.desc()).limit(500)
                .execution_options(esg_skip_scope=True)
            ).scalars().all()
        payload.append({
            "user_id": account.user_id,
            "username": account.username,
            "email": account.email,
            "full_name": account.full_name,
            "role": account.role,
            "created_at": account.created_at,
            "last_login_at": account.last_login_at,
            "is_active": account.is_active,
            "activity_events": [
                {"at": e.occurred_at, "action": e.action, "entity": e.entity_type}
                for e in events
            ],
        })

    audit.record(session, actor_principal.username, "privacy.subject_access",
                 detail={"subject_hash": subject_hash[:12], "accounts": len(accounts)})
    return payload
