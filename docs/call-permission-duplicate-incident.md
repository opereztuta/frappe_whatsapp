# Call-permission duplicate record incident — 2026-10-19

## Evidence and cause

The reported request failed with HTTP 417 while inserting a call-permission
message. The underlying MariaDB error was a duplicate primary key in
`WhatsApp Call Permission`, before the template reached its Meta message-send
operation.

The read-only investigation found local and production code at commit
`8ab7aef3100730d5a3d5c2b35e9fdcb522d995b3`. Production database contents were
not inspected. The failing sequence was reproduced locally in memory:

1. The external calling API supplies a phone number without a contact profile.
2. Its initial permission refresh inserts a phone/account record without a
   profile link.
3. The outgoing message's real `before_insert` hook resolves a stable profile.
4. The template's second permission refresh looks up only that profile, misses
   the phone record, and attempts the identical phone/account primary key.

The DocType declared `autoname: "hash"` while its controller generated a
fixed phone/account name. Frappe interpreted the collision as a random hash
collision and retried the same fixed name until the raw database error escaped.
Concurrency is not required to trigger the incident. The source app,
idempotency key, and language selection do not cause this lookup mismatch.

## Changes

Permission reads and writes share an account-scoped lookup across the supplied
profile, normalized phone, recipient, and legacy phone/account primary key.
All matches must identify one compatible record. Multiple records or populated
identifiers conflicting with the supplied identity raise validation errors;
there is no automatic merge or reassignment of unrelated profiles.

Updates attach missing identity fields and retain existing request timestamps
and message links when replacements are omitted. Existing record names remain
unchanged. New phone records retain their phone/account names; new phone-less
records use a deterministic SHA-256-derived account/recipient name. The DocType
uses controller naming instead of Frappe's random-hash collision retry mode.
Normal migration synchronizes this metadata.

Inserts use a savepoint. A duplicate-entry exception rolls back only to that
savepoint, then reloads and locks the winning identity record using current
reads. This avoids MariaDB repeatable-read snapshots hiding a newly committed
record. The incoming state is applied once to that record, preserving its
request history. Unrelated storage failures propagate. Existing request locks,
Meta checks, language selection, and API/idempotency contracts remain in place.

No change is required in `whatsapp_chat`, `zoni_edu`, or `zoni_crm_service`.
This patch does not implement general identity merging, historical duplicate
cleanup, or exactly-once delivery across external Meta sends and local commits.

## Regression validation

The permission DocType tests cover legacy phone/profile promotion, normalized
phones, missing legacy phone fields, profile-only lookup, legacy recipient
names, account isolation, conflicting records, unrelated storage errors, and
catchable primary-key collisions without hash retries.

The message integration regression uses real message insertion, profile
resolution, permission refresh/upsert, and call persistence, with Meta HTTP
mocked. It verifies the second refresh reuses the first record, one template is
sent, the request-message link survives subsequent refreshes, and idempotent
replay does not send again. Unrelated template provisioning and compliance
checks are isolated in the fixture.

The competing-insert regression uses two real database connections: the loser
establishes its initial snapshot, the winner inserts and commits, and the loser
attempts its insert. It exercises both phone and phone-less recipient naming,
then verifies one record and preservation of the winner's request timestamp.
Committed fixtures are explicitly cleaned up.

All **81 tests passed** on the isolated `call-permission-test.local` site:

| Module | Tests |
| --- | ---: |
| Permission DocType | 10 |
| Calling utilities | 38 |
| Calling API | 8 |
| Message DocType | 25 |

The site used a separate temporary MariaDB instance on loopback port 33329,
with the scheduler disabled and only Frappe and this app installed. The site
timezone and test process timezone were both UTC: existing calling tests use
host-local `datetime.fromtimestamp` alongside site-local Frappe datetimes.
Two existing tests initially failed with mismatched timezones and passed once
the isolated test environment used UTC consistently. No timestamp-conversion
behavior was changed in this patch.

From the local bench, run each module using:

```bash
TZ=UTC bench --site call-permission-test.local run-tests \
  --app frappe_whatsapp --skip-test-records --module <module>
```

The full module names are:

- `frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_call_permission.test_whatsapp_call_permission`
- `frappe_whatsapp.utils.test_calling`
- `frappe_whatsapp.frappe_whatsapp.api.test_calling`
- `frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.test_whatsapp_message`

A separate local metadata-sync check changed the test DocType back to its old
hash-naming settings, reloaded the reviewed DocType definition, and verified
custom naming was restored while an existing permission name was preserved.
Its committed fixtures were removed afterward. The temporary database server
was stopped after validation; reruns require starting that isolated instance.

Python compilation and `git diff --check` passed. Ruff syntax/undefined-name
checks passed for the changed utility and regression tests. The controller's
existing generated `DF.Literal` annotations are left unchanged.

## Manual deployment checks

1. Review and merge the local patch through the normal manual PR process.
   Record the previous revision and take the normal site backup.
2. Deploy the reviewed revision and run `bench --site <site> migrate` to sync
   `WhatsApp Call Permission` naming metadata. Clear caches and restart web and
   worker processes through the existing deployment process.
3. Verify the DocType has an empty `autoname` and `naming_rule` of `By script`.
   Existing names must remain unchanged. No data backfill is required.
4. With a designated test contact, verify a permission request succeeds, creates
   one permission record, and records its profile and request-message link.
   Replaying the same idempotency key must return the existing request.
5. Verify active permission still prevents a new permission template. Monitor
   Error Log for duplicate keys and identity-conflict validation failures.
   Investigate conflicting records individually; do not delete records or
   replay historical requests in bulk.

No production code or data was changed and no commit or deployment was made
as part of this implementation. If rolled back, restore the prior code and
DocType metadata through the normal migration/cache/restart process. Preserve
existing records; deterministic recipient names are ordinary document names
and remain readable by the prior recipient lookup.
