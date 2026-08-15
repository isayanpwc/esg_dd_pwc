# Deployment

What must be true before this tool sees a real target's data.

## 1. Environment

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | **Yes** in deployment | `postgresql+psycopg://user:pass@host/db`. Omitted, the tool falls back to a local SQLite file, which is for development only. |
| `ESG_DATA_KEYS` | **Yes** | `key-id:base64-32-byte-key`, comma separated. Retired keys must stay listed until their data is re-encrypted. |
| `ESG_ACTIVE_KEY_ID` | **Yes** | Which key new writes use. |
| `ESG_EMAIL_DOMAINS` | **Yes** | Allowlist for provisioning, e.g. `pwc.com`. Empty means no restriction — dev only. |
| `CLAUDE_API_URL` / `CLAUDE_API_KEY` | Optional | LLM-assisted mapping and narrative. Without them those steps fall back to deterministic logic. |
| `ESG_OCR_BACKEND` | Optional | `tesseract`, or unset. Unset means scanned pages are flagged for manual review rather than read as empty. |
| `ESG_RETENTION_DAYS_DOCUMENTS` | Optional | Default 2555 (7 years). |
| `ESG_RETENTION_DAYS_AUDIT` | Optional | Default 3650 (10 years). |

Generate a key:

```bash
python -m esg.db.crypto --generate
```

Losing `ESG_DATA_KEYS` means losing every encrypted field permanently. Store it
in a managed secret store, not in `.env` on a laptop.

## 2. Database

```bash
python -m alembic upgrade head
```

Revision `0002` enables row-level security on every deal-scoped table **on
Postgres only**. On SQLite the session-layer guard is the sole enforcement,
which is why SQLite is not for production.

### Row-level security contract

The application filter and the database policy are independent layers. For the
policy to apply, each transaction must set:

```sql
SET LOCAL esg.deal_ids = 'D001,D002';
SET LOCAL esg.all_deals = 'off';
```

A connection setting neither sees nothing. That is the intended failure mode:
a service that forgets the convention gets an empty result, not another deal's data.

Grant the application role no more than it needs, and never `SUPERUSER` or
`BYPASSRLS` — a superuser silently ignores every policy.

```sql
CREATE ROLE esg_app LOGIN PASSWORD '...';
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO esg_app;
REVOKE UPDATE, DELETE ON audit_event FROM esg_app;
```

## 3. Encryption at rest

Two distinct layers, both needed:

- **Field level** (this codebase): AES-256-GCM over PII and document paths.
  Protects against a leaked logical backup or a stray query in a log.
- **Storage level** (your infrastructure): volume or TDE encryption on the
  database and on document storage. Not something application code can provide.

## 4. First administrator

```bash
python -m esg.cli bootstrap-admin --email you@pwc.com --username you
```

Works only while the user table is empty, so it cannot be used as a later back
door. Everyone after that is invited:

```bash
python -m esg.cli invite --email colleague@pwc.com --role Analyst --as you
python -m esg.cli grant --deal D001 --user <user_id> --level Editor --as you
```

Roles are `Admin`, `Manager`, `Analyst`, `Viewer`. Deal levels are `Owner`,
`Editor`, `Reviewer`, `ReadOnly`. Role never widens deal visibility; only a
grant does.

## 5. SSO

`esg.security.provisioning.authenticate_sso` logs in a user the IdP has already
authenticated, matching on `idp_subject`. The account must already exist with a
role an Admin set — SSO authenticates, it does not authorise.

Wiring an IdP means: validate the assertion at your edge or in the Streamlit
front door, then call `authenticate_sso` with the verified subject. Do not
accept role or group claims from the IdP as authorisation without mapping them
explicitly to provisioned accounts.

## 6. Backups

- Nightly base backup plus WAL archiving; test a restore before go-live.
- Back up the key material separately from the database. A backup you cannot
  decrypt is not a backup.
- Verify the audit chain after any restore:

```bash
python -m esg.cli verify-audit
```

A broken chain after a restore means the restore was partial.

## 7. Retention

```bash
python -m esg.cli retention-report
python -m esg.cli retention-purge --confirm --dry-run --as you
```

Audit events are reported when past their window but never deleted — removing
one breaks verification for every later row. Archive the chain instead.

## 8. Pre-flight checklist

- [ ] `DATABASE_URL` points at Postgres, not SQLite
- [ ] `alembic current` shows head, and `0002` applied
- [ ] RLS confirmed: `SELECT relname, relrowsecurity FROM pg_class WHERE relrowsecurity`
- [ ] Application role lacks `BYPASSRLS`
- [ ] `ESG_DATA_KEYS` in a secret store; restore tested
- [ ] `ESG_EMAIL_DOMAINS` set to your tenancy
- [ ] Volume/TDE encryption on database and document storage
- [ ] `python -m esg.cli verify-audit` passes
- [ ] Independence and confidentiality review completed for the engagement
- [ ] A licensed peer dataset is loaded, or benchmarks are visibly labelled illustrative
