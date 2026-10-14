# Zoni CRM Service: business-scoped WhatsApp user IDs

This document is the implementation handoff for the `zoni_crm_service` team.
It describes the CRM work required to accept WhatsApp contacts that have a
phone number, a business-scoped user ID (BSUID), a parent BSUID, or any
explicitly linked combination of those identifiers.

The initial production path remains:

```text
Meta -> frappe_whatsapp -> zoni_edu -> zoni_crm_service
```

After the initial path is stable, CRM can receive the same signed version-2
events directly from `frappe_whatsapp`. Meta must remain subscribed only to
`frappe_whatsapp`; CRM must not add a second Meta webhook.

This is a CRM-owned implementation. No `zoni_crm_service` source is changed by
the Frappe BSUID work.

## October 14, 2026 generated call-permission messages

Local changes on Frappe `b937aef` and Zoni `2f28ec75` identify newly received
call-permission summaries as automated. CRM source is unchanged: its current
`apis/contactUs/lead/create` schema already accepts `isAutomatedMessage` and
maps it to the stored message automation flag.

| Layer | Field | Call-permission summary | Ordinary user message |
| --- | --- | --- | --- |
| WhatsApp Message | `is_automated_message` | Check value `1` | Default `0` |
| Signed version-2 envelope | `message.is_automated_message` | JSON `true` | JSON `false` |
| CRM intake request | `isAutomatedMessage` | JSON `true` | JSON `false` |

Frappe sets the flag only when handling Meta's structured
`interactive.type=call_permission_reply`. Both accepted and rejected summaries
are automated, including permanent and temporary acceptance. The message text,
identity, account, context and Meta message ID remain unchanged. Classification
does not inspect display text or sender names: user-written text saying “Call
permission accepted”, ordinary button replies, and list replies remain false.
This marks the generated summary, even though the permission decision itself
was made by the user.

After successful permission handling, Frappe now enqueues inbound forwarding
immediately instead of relying on recovery to discover the message. Existing
Meta-message and outbox-event deduplication remain in place. The flag is stored
before asynchronous forwarding, so reload and recovery retain it. No call is
automatically originated by this change.

Zoni maps the boolean from the incoming message to the top-level CRM field.
Legacy envelopes lacking the flag default to false; truthy strings such as
`"false"` do not enable it. Existing intake/profile-sync checkpoints and HMAC
verification are unchanged. Stored outbox payloads and their hashes are not
regenerated or rewritten.

The sandbox WhatsApp Message schema is migrated. The new Check field is hidden,
read-only, and defaults to zero; its controller annotation was generated with
Frappe's `TypeExporter`. Deploy Zoni's backward-compatible mapping and Frappe's
code/schema together through the normal migration and web/worker refresh
process. Rollback must preserve the database field, queued payloads, hashes,
and event checkpoints; reverting the mapping restores the previous unflagged
CRM behavior for subsequent deliveries.

Validation: 115 identity/message, routing/delivery, calling-webhook, Zoni
webhook/adapter, and event-integrity tests passed on an isolated MariaDB site
with external HTTP requests mocked or blocked. Added coverage verifies persisted
accepted/rejected flags, temporary/permanent cases, immediate enqueue, identical
user text remaining false, BSUID/parent/phone mappings, signed forwarding, and
completed duplicate requests making no additional CRM calls. Targeted Pyright
checks on the routing and related test files reported zero errors and warnings.
The isolated site's timezone matched the sandbox; optional HRMS installation
hooks were excluded. No acceptance message or call was sent to Meta or testcrm.

This is future-only behavior. Lucia Vargas's existing CRM message and other
historical messages were not reclassified, resent, or edited. Historical
corrections require a separate CRM-supported workflow with source evidence.
CRM, WhatsApp Chat, bridge/PBX configuration, Meta subscriptions, and production
remain unchanged.

## October 13, 2026 critical integration hardening

These changes are local and uncommitted on top of Frappe `14ad5bb` and Zoni
`d6ca6cb4`. CRM `whatsappBsuid` remains unchanged. WhatsApp Chat, the bridge,
PBX configuration, and Meta settings are unchanged by this work.

### Implemented behavior

- All Zoni incoming, identity-update, and status endpoints require the existing
  HMAC-SHA256 signature over timestamp plus exact body bytes. Missing receiver
  secret returns 503; missing/invalid/expired signatures return 403. A matching
  header/body event ID is mandatory (400 otherwise). Malformed and non-ASCII
  timestamp/signature values are rejected before persistence or CRM requests.
- Frappe never sends an unsigned client webhook, even when the historical
  `require_webhook_signature` flag is off. A missing sender secret is recorded
  as a failed delivery with bounded retries instead of making an HTTP request.
- Zoni serializes each event using a site/event-scoped MariaDB `GET_LOCK` on
  the request connection. A competing request returns retryable 503. The lock
  survives intake checkpoint commits; completion is committed before release.
  Connection loss aborts processing. Deployment requires MariaDB, with no
  expiring Redis lease or PostgreSQL fallback.
- Existing event IDs must match both stored body SHA-256 and event type before
  deduplication or retry. Changed bodies return terminal 409 and log event ID
  and hashes; original checkpoints/results remain unchanged. The unique-insert
  race uses a current database read and applies the same check. Historical
  hashes are not rewritten.
- Completed duplicates make no CRM request. Profile-sync retries skip accepted
  intake. Ambiguous intake failures automatically retry the same event, as
  selected for this release; rotations retain the previous lookup key.

### Sandbox configuration and acceptance

Signing is configured for client app
`zoni_crm_epTzT5AjLF6LdIBht7b1RydPAsH3LiIk`: its password-field secret matches
Zoni's `whatsapp_inbound_webhook_secret`, and both signature flags are enabled.
Secrets are not recorded here. The previous signing configuration is in the
owner-only local file `/tmp/bsuid-signing-before-20261013.json`.

Verified by October 13, 2026 at 20:37 UTC against `https://testcrm.zoni.edu/`:

| Case | Event ID | Account | CRM lead ID | Result |
| --- | --- | --- | --- | --- |
| Synthetic regular BSUID with parent metadata | `bsuid-synthetic-3afc8e59dedd4fc895d3db0d2a5894d9` | `12013920633` | 5285 | Intake and profile synchronization accepted; duplicate acknowledged |
| Synthetic parent-only BSUID | `bsuid-synthetic-bc8db41d1d714f61b02bc619031b228d` | `18299477544` | 5286 | Intake and profile synchronization accepted; duplicate acknowledged |

Both requests used the public sandbox endpoint, omitted phone destinations,
and have `crm_intake_completed=1`, `processed=1`, and empty `last_error`.
Subsequent identity updates omitting username, display name, and phone were
accepted for both existing records. Local contract tests verify omitted
fields are not sent to clear metadata; independent CRM database readback of
those metadata values was not performed. No Meta message or call was sent to
these synthetic identifiers.

Public endpoint checks returned 403 for an unsigned request and 409 for a
signed changed-body replay. Owner-only acceptance receipts are stored in
`/tmp/bsuid-critical-acceptance-20261013.json`.

All seven historical phone-hidden outbox failures were retried after correcting
signing and verifying the current adapter/mappings. All now have HTTP 200,
`Delivered`, two attempts, and completed intake/profile synchronization. Original
event IDs and payload bytes were preserved; no completed checkpoint was reset.
The deliveries are `k3jjiq8kb0`, `p3les7o71u`, `d9loe3ll8v`, `d00s35jotm`,
`h3s7176dq7`, `3nkk5fkbo1`, and `91er0vlork`. Evidence including hashes is in
`/tmp/bsuid-critical-recovery-20261013.json`. These are historical Meta-event
replays; a newly participant-originated live phone-hidden test was not performed.

### Scoped retries, deployment, and rollback

The sandbox global scheduler is disabled (`System Settings.enable_scheduler=0`),
which explains due retries not running automatically. It remains disabled.
A user cron entry marked `bsuid-whatsapp-crm-retry` runs every minute with
`flock`, targeting only the CRM client app. It calls:

```bash
cd /home/oscar/frappe-bench
env/bin/bench --site zoni.local execute frappe_whatsapp.utils.client_delivery.retry_failed_client_events --kwargs '{"client_app":"zoni_crm_epTzT5AjLF6LdIBht7b1RydPAsH3LiIk"}'
```

The optional `client_app` argument scopes both unqueued-message recovery and
outbox selection; omitting it preserves the existing general scheduler hook.
Empty scope arguments fail instead of becoming unscoped. Transport errors,
429, and 5xx remain retryable within the existing eight-attempt limit; other
4xx responses require operator correction. Existing backup cron entries were
preserved; the previous crontab is `/tmp/bsuid-crontab-before-20261013.txt`.
Output goes to `logs/whatsapp_crm_retry.log`.

Cron/worker acceptance used delivery `o0k47c37j5`, queued as due without an
initial enqueue. Cron delivered it in one attempt and received HTTP 200 with
`deduplicated=true` for the completed synthetic regular event.

For deployment, configure matching secrets for every affected active sender
and receiver before enforcing the new code, then restart web/worker processes
through the normal release process. No DocType migration is required. Use the
existing global hook where the production scheduler is enabled; the scoped
cron is a sandbox-specific alternative, not an instruction to edit production.

For rollback, stop affected forwarding and remove only the cron line marked
`bsuid-whatsapp-crm-retry`, preserving unrelated entries. Do not restore an
unsigned receiver or clear event records, payload hashes, or intake checkpoints.
If old code must be restored, keep the receiver secret and both flags enabled;
keep forwarding paused until authenticated processing is verified again.
Investigate 409 collisions rather than altering historical payloads or hashes.

Validation: 105 identity, message, routing, delivery, Zoni webhook/adapter, and
event-integrity tests passed with external requests mocked on an isolated
MariaDB test site. Tests cover real two-connection lock contention, persistence
across checkpoint commits, disconnected lock release, collisions before/after
completion, unique-insert races, and unchanged automatic retry requests.
The disposable Zoni installation lacks optional HRMS setup; no global
before-test hooks or tests were run against the working sandbox database.

The local concurrency and authentication blockers are addressed. Exactly-once
CRM effects after lost responses remain unproven: historical-alias lookup and
durable event idempotency remain CRM-owned dependencies. This work does not
resolve the CRM calling/messaging blockers listed in the audit or authorize
production deployment.

## October 12, 2026 sandbox adapter update

Reviewed source revisions: `frappe_whatsapp` `4da4304`, `zoni_edu`
`f19a69f4`, `whatsapp_chat` `50cf336`, bridge `aebe9aa`, and CRM `bd38fb3`.
The Frappe/Zoni changes described here are uncommitted local changes on those
bases. Earlier sections describing aliases and the CRM event ledger remain
CRM-team requirements, not capabilities supplied by the new update endpoint.

The active sandbox account is `12013920633`, portfolio `308031774557009`.
Its mapped CRM channel is `d110c46c-1ea2-4a38-a070-d05337c80000`; the channel
UID in the CRM team's example must not replace that account mapping.

Deploy with the normal Frappe `bench --site <site> migrate` procedure so the
Zoni **WhatsApp Inbound Event** DocType gains `crm_intake_completed` and
`crm_intake_result`. Restart application processes through the normal local
service procedure after deploying Python changes. The sandbox DocType was
synchronized directly during validation; Meta subscriptions were unchanged.

Incoming delivery now performs CRM intake, durably checkpoints the returned
CRM result, then synchronizes the channel user's profile. A failed second
operation returns 502 and leaves the event unprocessed. Retry skips accepted
intake and resumes synchronization. A completed duplicate makes no CRM request.
Legacy events without an event ID cannot use this durable checkpoint. A lost
intake response before checkpointing still requires CRM-side idempotency.

Phone-hidden omissions preserve stored data: unavailable optional fields are
omitted from the update request. Parent IDs retain their exact `.ENT.` format.
Profile display names are included in the Frappe identity snapshot. Identity
transitions are never inferred from usernames or human-readable system text.

### Validation evidence and remaining acceptance

- Real regular-BSUID-only message `b6flmpguj7` was delivered and read; its
  original phone destination stayed empty after status replay.
- Phone-hidden regular-plus-parent dashboard payload passed isolated Frappe
  processing with external forwarding mocked and test records rolled back.
- Identity-update adapter and two-stage webhook tests cover account isolation,
  metadata omission, previous/current lookup keys, rejected responses, durable
  synchronization retry, completed duplicates, and lost rotation responses.
- The update endpoint initially returned HTTP 404, then became available on
  testcrm. A later profile-sync retry returned `success: true` for regular BSUID
  `US.1354806593212850` on channel `d110c46c-1ea2-4a38-a070-d05337c80000`.
  This confirms existing-user profile synchronization, not full phone-free
  intake or live parent-BSUID messaging. No WhatsApp message was sent by that
  synchronization test.
- For remaining acceptance, validate an approved phone-free contact on the sandbox
  channel: accepted intake, parent/name/handle synchronization, same channel-user
  record, retry after forced synchronization failure, and a regular-BSUID reply.
  Never use Meta dashboard sample IDs as live message destinations.
- Calling remains deferred: the reviewed CRM call service still requires a
  phone and creates fresh retry keys for call mutations.

### Deferred PBX calling configuration: operator handoff

The future operator runbook is
[`docs/whatsapp-bsuid-calling.md`](../../../../asterisk-voice-agent-bridge/docs/whatsapp-bsuid-calling.md)
in the sibling `asterisk-voice-agent-bridge` repository. Its local path is
`/home/oscar/asterisk-voice-agent-bridge/docs/whatsapp-bsuid-calling.md`.
It contains preflight commands, the required recording-aware deployment copy,
backup/install/reload steps, attended acceptance, and rollback. Configuration
changes and live calls require separate authorization and a maintenance window;
the route has now been deployed under explicit user authorization; ongoing
sandbox/CRM enablement remains deferred.

Read-only PBX inspection on October 12, 2026 confirmed Asterisk 22.8.2,
FreePBX 17.0.28, loaded base64/string modules, and the FreePBX include chain
`from-internal` → `from-internal-xfer` → `from-internal-custom`. The named
BSUID route and `/etc/asterisk/extensions_whatsapp_bsuid.conf` were absent.
Extension 847 was registered and mapped in Frappe to `operez@zoni.edu`.
The existing numeric WhatsApp route performs caller initialization and outbound
recording checks; the future BSUID route must follow that recording policy
using the local call ID as the destination label. The local dialplan asset now includes those steps. Five local contract checks
and the mocked Frappe calling suites validated preparation. The installed
Asterisk route and attended regular-BSUID call have now passed runtime acceptance. The artifact is
prepared on bridge base revision `aebe9aad9f24a186226988337ce9144cf69c9a4c` with
SHA-256 `d6efa083cc04f55b154ab48f1adf8100719f92f3c19a0256231fcbb78bbd57ff`.

### October 13 dedicated-route deployment and acceptance

The user authorized continuing with active production calls and confirmed that
both participants were ready and agreed to recording. The BSUID route was
installed and FreePBX reloaded with 18 active calls present. Backup:
`/var/backups/asterisk/bsuid-20261013T151814Z`. The new file is
`asterisk:asterisk`, mode `0644`; the custom include file's mode `0664` and
existing contents were preserved, with exactly one BSUID include appended.
Both route lookups succeeded. The numeric route was unchanged apart from
regenerated source line numbers. FreePBX emitted a helper error for a quoted
absolute-path scripter include already present in the backup; it was left
unchanged, and both attended call tests passed.

- BSUID call `ucuanuid0u`: account `18299477544`, agent `operez@zoni.edu`,
  extension 847, exact regular BSUID, and **empty phone destination**.
  The WhatsApp trunk answered at 15:20:22 UTC. The participant confirmed handset
  ringing and two-way audio, then ended the call.
- Recording: 23.4-second WAV with nonzero audio samples; filename uses the local
  call ID rather than the BSUID. The runtime trace confirms caller and recording
  subroutines executed before direct BSUID dialing.
- Numeric regression `vnj49doevl`: existing numeric route, confirmed ringing and
  two-way audio, plus a 25.84-second WAV with nonzero audio samples.
- Both test channel groups ended. The sandbox BSUID destination was restored to
  its prior disabled state; the PBX route remains installed. Ongoing enablement
  is still a separate decision. No production Frappe settings, trunk credentials,
  AMI permissions, or CRM source were changed.

Frappe records remain `PBX Queued`, which represents AMI acceptance only. The
answered calls are proven by PBX evidence and participant confirmation. Final
`DIALSTATUS` and hangup cause were not captured, and terminal Frappe status
correlation is a follow-up. Parent BSUIDs have local contract coverage but were
not tested live. CRM phone-optional calling and stable retry-key work also
remain deferred. See the PBX runbook for full evidence and rollback instructions.


## Reviewed compatibility baseline

This contract was reviewed against these revisions:

| Repository | Branch | Revision |
| --- | --- | --- |
| `frappe_whatsapp` | `feature/business-scoped-user-ids` | `212a75b79f34` |
| `zoni_edu` | `feature/business-scoped-user-ids` | `88386c0468e3` |
| `whatsapp_chat` | `feature/business-scoped-user-ids` | `50cf336ab4cc` |
| `asterisk-voice-agent-bridge` | `feature/business-scoped-user-ids` | `aebe9aad9f24` |
| `zoni_crm_service` | `main` | `56baa262dfae` |

Revalidate request and response examples if any of these revisions changes.

## Ownership and trust boundaries

- `frappe_whatsapp` owns the Meta webhook, identity resolution, Meta access
  tokens, outbound WhatsApp API calls, and the AMI originate request.
- `zoni_edu` verifies Frappe webhook signatures, durably deduplicates events,
  translates version-2 events into the current CRM API, and returns success to
  Frappe only after CRM accepts the event.
- CRM owns leads, CRM-scoped aliases, messages, event deduplication, conflict
  reconciliation, outbound intent, and the agent UI.
- CRM calls Frappe for WhatsApp messages and calls. It must never call Meta,
  Asterisk, or FreePBX directly and must not store Meta, AMI, or SIP secrets.
- `whatsapp_chat` is not a CRM dependency. Its phone-optional display and
  profile/account behavior are a reference for the corresponding CRM UX.
- The Go voice-agent bridge is not in the outbound WhatsApp call path. Its
  repository owns the reviewed FreePBX BSUID dialplan and operator runbook.

## Identity rules

CRM must use the following rules consistently in intake, search, messaging,
calling, status handling, and display:

1. The stable CRM record is the lead, not a phone number or username.
2. Identity is scoped by `CRM_PROVIDER_CHANNEL_ID`. Never match an alias from
   one channel to a lead in another channel.
3. Supported alias types are `phone`, `user_id`, and `parent_user_id`.
4. Normalize phones to one E.164 form before lookup or storage.
5. Treat BSUIDs as case-sensitive ASCII values. A regular BSUID matches
   `^[A-Z]{2}\.[A-Za-z0-9]{1,128}$`; a parent BSUID matches
   `^[A-Z]{2}\.ENT\.[A-Za-z0-9]{1,128}$`.
6. `username` is mutable display metadata and is never a deduplication key.
7. An inbound `providerUserId` is selected in this order: regular `user_id`,
   parent `parent_user_id`, then phone.
8. For outbound operations, use a phone when available; otherwise use the
   active regular BSUID, then the active parent BSUID.
9. Retain rotated BSUIDs as inactive aliases. Historical events must continue
   to resolve through them.
10. Link aliases only when one explicit Meta event supplies them together, an
    identity-update event links the previous and current values, or a
    `REQUEST_CONTACT_INFO` response explicitly links the voluntarily shared
    phone to the sender.

Do not infer a phone from a BSUID, merge by username, or merge across provider
channels even when values happen to match.

## Required CRM data model

Apply equivalent changes to both the CRM base schema and its production delta
migration.

The current CRM implementation points that require coordinated changes are:

- `web/src/migration/tables.sql` and `web/src/migration/delta.sql` for the
  additive schema and backfill;
- `web/src/entities/channel.ts`, `web/src/repository/users.ts`, and
  `web/src/services/leadCreateUsingContactUs.ts` for phone-optional identity
  intake and alias-based deduplication;
- `web/src/provider/zoniEdu.ts`, `web/src/services/messageCreate.ts`, and
  `web/src/services/whatsappCall.ts` for outbound messaging and calling; and
- the lead profile/calling components for display and validation changes.

Keep identity resolution in one service/repository layer shared by the
phase-one API routes and phase-two direct webhooks.

### Lead compatibility fields

- Widen `crm_leads.PROVIDER_USER_ID` from `VARCHAR(50)` to `VARCHAR(191)`.
- Keep `PROVIDER_USER_HANDLE` as display metadata.
- The database already permits a null phone, but the TypeScript `ICrmLead`
  model and validation paths must also make `phone` optional/null-safe.
- Add `WABAZ` to the provider-ID-capable channel list so a BSUID-only contact
  does not require an email or phone.
- Stop deduplicating WABAZ contacts by `(provider, providerUserId)`. The alias
  table below becomes authoritative because provider IDs can rotate.

### Provider identity aliases

Add a table equivalent to `crm_provider_identity_aliases` with:

| Column | Requirement |
| --- | --- |
| Primary key | Auto-increment CRM alias ID |
| `CRM_LEAD_ID` | Required owner lead |
| `CRM_PROVIDER_CHANNEL_ID` | Required identity scope |
| `IDENTITY_TYPE` | `phone`, `user_id`, or `parent_user_id` |
| `IDENTITY_VALUE` | Normalized value, up to 191 ASCII characters |
| `IS_ACTIVE` | Current alias marker; previous rotated IDs remain inactive |
| Audit fields | Existing CRM `CROPER`, `CRTIME`, `LASTOPER`, and `LASTTIME` conventions |

Use a binary/case-sensitive collation for `IDENTITY_VALUE` and enforce:

```text
UNIQUE (CRM_PROVIDER_CHANNEL_ID, IDENTITY_TYPE, IDENTITY_VALUE)
INDEX  (CRM_LEAD_ID, CRM_PROVIDER_CHANNEL_ID, IS_ACTIVE)
```

The unique key applies to inactive aliases too. An old BSUID must never be
reassigned silently to another lead.

### Provider event ledger and conflict quarantine

Add a durable event table equivalent to `crm_provider_events` with:

- provider channel ID and provider event ID;
- event type and SHA-256 hash of the canonical received payload;
- processing state such as `PROCESSING`, `PROCESSED`, `CONFLICT`, or `FAILED`;
- raw JSON payload;
- associated lead/message IDs when known;
- involved lead IDs and conflict reason when quarantined;
- attempt, error, creation, processing, and update timestamps.

Enforce a unique key on `(CRM_PROVIDER_CHANNEL_ID, PROVIDER_EVENT_ID)`. The
ledger is required even though Zoni already deduplicates events: it protects
CRM-side retries and is reused by the future direct webhook path.

A duplicate event ID with the same payload hash returns its stored result. The
same event ID with a different hash is an integration incident and must not be
processed as a new event.

### Message audit fields

Add fields equivalent to:

- `PROVIDER_RECIPIENT_TYPE`: `phone`, `user_id`, or `parent_user_id`;
- `PROVIDER_RECIPIENT_VALUE`: the exact selected outbound identity;
- `PROVIDER_EXTERNAL_REFERENCE`: the stable reference sent to Frappe.

Keep `crm_messages.PROVIDER_PHONE` phone-only for compatibility. Do not put a
BSUID into that column. Enforce uniqueness of the external reference within a
provider channel when it is present.

CRM must reserve and persist an outgoing message/reference before making the
remote Frappe request. If an HTTP response is lost, retry the same logical send
with the same external reference rather than creating a new reference.

## Phase-one Zoni-to-CRM API contract

Zoni authenticates these requests with its existing Bearer token. CRM routes
continue to use the existing response wrapper:

```json
{
  "success": true,
  "data": {}
}
```

Zoni treats `success: false` as rejection even if the HTTP response itself is
2xx. It then returns 502 to Frappe, leaving the Frappe outbox event retryable.
Return `success: true` only after the CRM transaction has committed or the
event has been durably quarantined.

### Incoming message

```http
POST /apis/contactUs/lead/create
Authorization: Bearer <API_SECRET_FOR_APPS>
Content-Type: application/json
```

Example BSUID-only request produced by `zoni_edu`:

```json
{
  "firstName": "example_user",
  "middleName": "",
  "lastName": "",
  "message": "Hello",
  "crmProviderChannelUid": "11111111-2222-3333-4444-555555555555",
  "providerMessageId": "wamid.example",
  "providerUserId": "US.AbCd1234",
  "providerUserHandle": "example_user",
  "providerIdentityAliases": [
    {"type": "user_id", "value": "US.AbCd1234"},
    {"type": "parent_user_id", "value": "US.ENT.Parent1234"}
  ],
  "providerEventId": "2fbd6f6ebfbf3b2b7f5be2da105a321f",
  "ip": "",
  "providerUserJSON": {
    "event": "whatsapp.incoming",
    "message": {},
    "payload": {}
  },
  "providerMessageJson": {}
}
```

When known, Zoni also supplies `phone` in E.164 form and includes a phone
entry in `providerIdentityAliases`. `phone` must remain optional. The route
must accept and validate:

- `providerEventId`;
- `providerIdentityAliases[]` objects containing `type` and `value`;
- `providerUserHandle`;
- `providerUserId` up to 191 characters.

The success body must retain the identifiers already consumed by Zoni:

```json
{
  "success": true,
  "data": {
    "crmLeadId": 123,
    "crmLeadUid": "lead-uid",
    "crmUserId": 456,
    "crmMessageId": 789,
    "eventStatus": "processed"
  }
}
```

### Identity and profile updates

The implemented CRM endpoint is:

```http
POST /apis/contactUs/channelUser/update
Authorization: Bearer <API_SECRET_FOR_APPS>
Content-Type: application/json
```

Zoni sends:

```json
{
  "crmProviderChannelUid": "11111111-2222-3333-4444-555555555555",
  "providerUserId": "US.Old1234",
  "update": {
    "providerUserId": "US.New1234",
    "parentProviderUserId": "US.ENT.NewParent",
    "providerUserHandle": "new_handle",
    "providerUserName": "Maria G",
    "phone": "13055551234"
  }
}
```

Top-level `providerUserId` is the lookup key: previous regular BSUID, then
previous parent BSUID, then current regular/parent identity. For post-intake
synchronization, it is exactly the identity supplied to intake (including a
phone for legacy phone-only intake). `update.providerUserId` selects the current
regular BSUID, otherwise parent BSUID, otherwise the known phone for legacy
phone-only events. Only known, explicitly linked phones are forwarded using
Zoni's existing E.164 normalization. Unavailable optional fields are omitted.

The endpoint updates an existing channel user, returns the CRM response wrapper,
and does not accept an event ID or implement historical aliases. Zoni requires
`success: true`, including when the HTTP response is 200. Frappe/Zoni retain
their existing event IDs and retry ledger locally.

A successful rotation overwrites the lookup ID. If its response is lost, a
retry using the previous ID can fail. Zoni retains that event and its error for
manual reconciliation; it does not guess a replacement key, create a new user,
or report uncertain success. CRM-owned follow-up is event-idempotent updates,
historical aliases, conflict quarantine, and safe handling of reordered
rotations. This endpoint alone does not complete those requirements.

### Message status

```http
POST /apis/leads/message/statusUpdate
Authorization: Bearer <API_SECRET_FOR_APPS>
Content-Type: application/json
```

Example request:

```json
{
  "crmProviderChannelUid": "11111111-2222-3333-4444-555555555555",
  "providerMessageId": "wamid.example",
  "status": "delivered",
  "time": "2026-10-01T12:00:00Z",
  "oper": "SYSTEM",
  "statusJson": {
    "event": "whatsapp.message_status",
    "eventId": "7ef59a82fb6580918eb8f03d51b12851",
    "messageName": "local-frappe-message",
    "sourceApp": "crm-client-app",
    "externalReference": "crm-message-reference",
    "previousStatus": "sent",
    "currentStatus": "delivered",
    "normalizedStatus": "delivered"
  }
}
```

Use `statusJson.eventId` as the phase-one event ID. Match the message by
provider channel plus `providerMessageId`, falling back to the stored external
reference when necessary. Phone is not a valid status correlation key.
Repeated or out-of-order statuses must not create messages or regress a later
terminal status.

## Transactional identity intake

Process an incoming or identity-update event in one database transaction:

1. Resolve `crmProviderChannelUid` to one provider channel.
2. Normalize and validate every supplied alias. Reject duplicate alias types
   with conflicting values in one request.
3. Claim `(channel, providerEventId)` in the provider-event ledger and store
   the payload hash and raw payload.
4. Lock the matching alias rows in a deterministic order.
5. When no alias resolves, create one lead and attach all explicitly linked
   aliases.
6. When every alias resolves to one lead, reuse that lead and attach any new
   aliases.
7. When aliases resolve to multiple leads, do not create or merge a lead and
   do not reassign aliases. Mark the event `CONFLICT`, store the involved lead
   IDs and raw evidence, and return a committed success response containing
   `eventStatus: "conflict_quarantined"`.
8. Create or update the CRM message only after identity resolution succeeds.
9. Mark the event `PROCESSED` and commit before returning `success: true`.

CRM does not currently have a safe general lead-merge service, so automatic
lead merging is outside this release. Provide an administrator-only conflict
view or report plus a reconciliation action that:

- selects a canonical lead;
- explicitly reassigns or closes the conflicting CRM data under CRM policy;
- attaches the aliases to the canonical lead;
- resets the stored event for replay; and
- replays the original payload exactly once without changing its event ID.

Quarantine is an accepted durable state, not data loss. The raw event remains
available until reconciliation and replay succeed.

## Outbound messages

### Existing direct-create integration

`POST /api/resource/WhatsApp Message` also returns known recipient identities
in its `data` document. For new outgoing messages sent using `to`, Frappe
fills `recipient_user_id` and `recipient_parent_user_id` from the resolved
contact profile when Meta's immediate send response does not supply them.
When `recipient` was omitted, it contains the regular BSUID, falling back to
the parent BSUID. An explicitly supplied `recipient` is preserved. The field
is spelled `recipient`, not `receipient`.

The phone still takes precedence for sending when `to` and `recipient` are
both present. These response fields are persisted on the message before the
creation response is returned. Later saves do not refresh this snapshot from
the profile; status webhooks can still update the recipient identity fields
with Meta-reported values. If neither the scoped profile nor Meta knows a
BSUID, the identity fields remain empty. There is no backfill of older
messages and no BSUID inferred from a phone alone.

### Recommended idempotent send API

Replace the legacy `POST /api/resource/WhatsApp Message` integration with:

```http
POST /api/method/frappe_whatsapp.frappe_whatsapp.api.v1.messages.send
Authorization: token <frappe-api-key>:<frappe-api-secret>
Content-Type: application/json
```

The authenticated Frappe user must be bound to exactly one enabled **WhatsApp
Client App**, and the selected WhatsApp Account must be in that app's allowed
accounts.

Example BSUID-only send:

```json
{
  "external_reference": "crm-message-550e8400-e29b-41d4-a716-446655440000",
  "content_type": "text",
  "recipient": "US.AbCd1234",
  "whatsapp_account": "18299477544",
  "source_app": "crm-client-app",
  "message": "Hello"
}
```

Supported destination fields are:

| Field | Meaning |
| --- | --- |
| `to` | Phone destination |
| `recipient` | Regular or parent BSUID |

At least one is required. If both are supplied, Frappe sends `to`, matching
Meta's precedence rule. CRM should normally send only the selected field.

Other supported request fields are `content_type`, `attachment_url`,
`template`, `body_param`, and `buttons`. Authentication/OTP templates require
`to`; reject a BSUID-only authentication send in CRM before calling Frappe.

A successful Frappe method response wraps this result in `message`:

```json
{
  "message": {
    "ok": true,
    "message_name": "local-frappe-message",
    "provider_message_id": "wamid.example",
    "external_reference": "crm-message-550e8400-e29b-41d4-a716-446655440000",
    "status": "Success",
    "recipient_type": "user_id",
    "recipient": "US.AbCd1234",
    "idempotent_replay": false
  }
}
```

Idempotency is scoped by client app, WhatsApp Account, and external reference.
Persist the external reference before the first request and reuse it after a
timeout or retry. Store the returned Frappe message name, provider message ID,
selected recipient type/value, status, and replay flag.

## Outbound calling

Use the existing calling endpoints:

```text
GET  /api/method/frappe_whatsapp.frappe_whatsapp.api.calling.get_call_state
POST /api/method/frappe_whatsapp.frappe_whatsapp.api.calling.request_call_permission
POST /api/method/frappe_whatsapp.frappe_whatsapp.api.calling.start_outbound_call
```

Every request requires one identity:

- `phone_number` for a phone; or
- `recipient` for a regular or parent BSUID.

When both are supplied, `phone_number` wins. CRM must resolve
`agent_extension` on the server from the authenticated agent; never trust a
browser-supplied extension. Continue to send the channel's WhatsApp Account,
the CRM client app as `source_app`, and the lead UID as
`external_reference`.

Permission and call-start mutations also require an `idempotency_key`. Store
the key with the logical action and reuse it after an uncertain response. A
new intentional permission request or call attempt gets a new key.

For BSUID calls, Frappe safely encodes the identity into AMI variables and
uses `whatsapp-bsuid@from-internal`. CRM must not construct AMI variables,
dialplan extensions, SIP destinations, or dial prefixes. The deployment and
staged-ring procedure is in the `asterisk-voice-agent-bridge` repository at
`docs/whatsapp-bsuid-calling.md`.

`pbx_queued` proves only that AMI accepted the originate. BSUID calling is not
accepted until an approved regular BSUID-only test user rings and Asterisk
evidence correlates that attempt with the Frappe WhatsApp Call ID. Run one
numeric WhatsApp call afterward to prove the existing route is unchanged.

See [the detailed CRM calling guide](./zoni-crm-whatsapp-calling.md) for the
authentication, permission state machine, and production configuration.

## CRM user experience

Remove phone-only assumptions from WABAZ lead validation, chat, and calling.
Use this display fallback:

```text
lead name -> provider username -> phone -> masked BSUID
```

Mask a BSUID so the UI does not expose the full opaque identifier in list
views or notifications. The full value may be available in an authorized
technical detail view for support.

- Permit WABAZ leads and conversations without a phone.
- Enable WhatsApp messaging and calling when a usable BSUID exists.
- Disable phone-specific actions when no phone alias exists.
- Label actions as WhatsApp messaging/calling rather than phone messaging or
  phone calling.
- Do not show a BSUID under a label such as **WhatsApp #**.
- Treat username changes as display updates, not new contacts.

## Configuration and secrets

Never commit any value in the following table.

| Phase | System | Setting | Purpose |
| --- | --- | --- | --- |
| 1 | CRM | `API_SECRET_FOR_APPS` | Existing Bearer token accepted from Zoni |
| 1 | Zoni site config | `zoni_crm_url` | CRM base URL |
| 1 | Zoni site config | `zoni_crm_token` | Must match the CRM app secret |
| 1 | Frappe Client App | App ID and webhook secret | Signs Frappe-to-Zoni version-2 events |
| 1 | Zoni site config | `whatsapp_inbound_app_id` | Must match the Frappe Client App ID |
| 1 | Zoni site config | `whatsapp_inbound_webhook_secret` | Must match the Frappe webhook secret |
| 1 | Zoni site config | `whatsapp_require_signed_webhooks` | Enable after one signed sandbox delivery succeeds |
| 2 | CRM secret manager | `WHATSAPP_INBOUND_APP_ID` | Expected direct Frappe app ID |
| 2 | CRM secret manager | `WHATSAPP_INBOUND_WEBHOOK_SECRET` | Direct webhook HMAC secret |
| 2 | CRM configuration | WhatsApp Account to provider-channel mapping | Maps event scope to `CRM_PROVIDER_CHANNEL_ID` |

Use distinct secrets for the Zoni-to-CRM Bearer token and the Frappe webhook
HMAC. Rotate them independently. Redact authorization and signature values
from logs.

## Phase-two direct Frappe-to-CRM delivery

After phase one is stable, implement:

```text
POST /apis/webhooks/whatsapp/inbound
POST /apis/webhooks/whatsapp/status
```

The inbound endpoint accepts `whatsapp.incoming` and
`whatsapp.identity_updated`. The status endpoint accepts
`whatsapp.message_status`. Both consume the same version-2 envelopes already
received by Zoni and feed the phase-one identity/event services rather than
creating a second implementation.

Treat these envelopes as additive: validate the required fields, preserve the
raw body, and ignore unknown fields rather than rejecting a compatible future
sender.

Representative incoming envelope:

```json
{
  "schema_version": 2,
  "event": "whatsapp.incoming",
  "event_id": "2fbd6f6ebfbf3b2b7f5be2da105a321f",
  "occurred_at": "2026-10-01 12:00:00",
  "app_id": "crm-client-app",
  "whatsapp_account": "18299477544",
  "message": {
    "name": "local-frappe-message",
    "message_id": "wamid.example",
    "from": null,
    "from_user_id": "US.AbCd1234",
    "from_parent_user_id": "US.ENT.Parent1234",
    "username": "example_user",
    "contact_profile": "whatsapp-profile-name",
    "identity": {
      "profile_id": "whatsapp-profile-name",
      "phone": null,
      "user_id": "US.AbCd1234",
      "parent_user_id": "US.ENT.Parent1234",
      "username": "example_user",
      "preferred_recipient": "US.AbCd1234"
    },
    "whatsapp_account": "18299477544",
    "content_type": "text",
    "message": "Hello",
    "timestamp": "2026-10-01 12:00:00",
    "contact_payload": null,
    "contact_origin": null
  }
}
```

Representative identity-update envelope:

```json
{
  "schema_version": 2,
  "event": "whatsapp.identity_updated",
  "event_id": "86d6fd68fbb80a50f5aa95f980d45daf",
  "occurred_at": "2026-10-01 12:05:00",
  "app_id": "crm-client-app",
  "whatsapp_account": "18299477544",
  "identity": {
    "profile_id": "whatsapp-profile-name",
    "phone": null,
    "user_id": "US.New1234",
    "parent_user_id": "US.ENT.NewParent",
    "username": "new_handle",
    "preferred_recipient": "US.New1234"
  },
  "previous_user_id": "US.Old1234",
  "previous_parent_user_id": "US.ENT.OldParent"
}
```

Representative status envelope:

```json
{
  "schema_version": 2,
  "event": "whatsapp.message_status",
  "event_id": "7ef59a82fb6580918eb8f03d51b12851",
  "occurred_at": "2026-10-01 12:06:00",
  "app_id": "crm-client-app",
  "whatsapp_account": "18299477544",
  "message": {
    "name": "local-frappe-message",
    "message_id": "wamid.example",
    "external_reference": "crm-message-reference",
    "source_app": "crm-client-app",
    "to": "",
    "recipient": "US.AbCd1234",
    "recipient_user_id": "US.AbCd1234",
    "recipient_parent_user_id": "",
    "contact_profile": "whatsapp-profile-name",
    "identity": {
      "profile_id": "whatsapp-profile-name",
      "phone": null,
      "user_id": "US.AbCd1234",
      "parent_user_id": null,
      "username": "example_user",
      "preferred_recipient": "US.AbCd1234"
    },
    "previous_status": "sent",
    "current_status": "delivered",
    "normalized_status": "delivered"
  }
}
```

### Signature verification

Read the raw request bytes before JSON parsing and require:

```text
X-WhatsApp-App-ID
X-WhatsApp-Event-ID
X-WhatsApp-Timestamp
X-WhatsApp-Signature: sha256=<lowercase hex digest>
```

Reject the request unless:

1. the app ID matches the configured value;
2. the header event ID exactly matches the body `event_id`;
3. the timestamp is an integer no more than 300 seconds from CRM time; and
4. the signature matches HMAC-SHA256 over the exact bytes
   `<timestamp>.<raw request body>` using a constant-time comparison.

Do not parse and reserialize the JSON before verifying it. A retry has a new
timestamp and signature but the same stable event ID and payload.

### Direct response semantics

| Result | HTTP behavior |
| --- | --- |
| Committed event | 2xx |
| Same event ID and payload hash | 2xx with `deduplicated: true` |
| Durably quarantined conflict | 2xx with `conflict_quarantined: true` |
| Invalid event schema or unknown account mapping | 400 |
| Invalid app ID/signature | 401 or 403 |
| Same event ID with a different payload hash | 409 and alert |
| Temporary backpressure | 429 |
| Temporary database/server failure | 5xx |

Frappe retries transport errors, 429, and 5xx responses. Other 4xx responses
are terminal and require correction plus a manual retry from the Frappe
delivery record.

### Cutover and rollback

1. Validate all recorded BSUID fixtures against the direct endpoints in the
   sandbox while production still points to Zoni.
2. Confirm CRM event counts, lead resolution, messages, statuses, and
   quarantined conflicts match the Zoni path.
3. Update both the inbound and status URLs on the Frappe Client App to the CRM
   endpoints as one maintenance-window change.
4. Keep the same app ID, event subscriptions, allowed accounts, and webhook
   secret; require signatures.
5. Monitor event latency, duplicates, conflicts, terminal failures, and
   retryable failures.
6. Roll back by restoring both URLs to Zoni. Stable event IDs prevent a replay
   from creating duplicate CRM messages.
7. After seven clean days, disable the Zoni WhatsApp forwarding routes. Keep
   them for one release as rollback code before removing only that bridge.

Meta's webhook destination does not change during this cutover.

## Migration procedure

1. Back up the CRM database.
2. Run a read-only collision report grouped by provider channel, normalized
   phone, regular BSUID, and parent BSUID.
3. Resolve malformed values and document collisions before adding the unique
   alias constraint.
4. Deploy the additive tables and columns first.
5. Backfill WABAZ phone aliases and any valid existing provider IDs in bounded
   batches. Do not emit provider events during backfill.
6. Deploy alias-based intake, event deduplication, identity updates, and
   phone-optional UI behavior.
7. Run the migration/backfill a second time and verify that counts and alias
   ownership do not change.
8. Enable BSUID-only sandbox delivery before production delivery.

Do not roll back by deleting aliases or event records. An application rollback
should leave the additive CRM schema in place so old code can ignore it and a
fixed release can reuse the identity history.

## Acceptance checklist

### Identity and intake

- [ ] Phone plus regular BSUID creates one lead with both aliases.
- [ ] BSUID-only username creates a lead and message without a phone.
- [ ] Regular and parent BSUIDs attach to one lead.
- [ ] Username changes update display metadata without creating a lead.
- [ ] BSUID rotation retains old/new aliases and message continuity.
- [ ] A contact-request reply links the voluntarily shared phone.
- [ ] No alias resolves across provider channels.
- [ ] Concurrent duplicate events create exactly one lead and message.
- [ ] Multi-lead alias collisions quarantine without creating another lead.
- [ ] Reconciliation replays the quarantined event exactly once.

Use the recorded fixtures under `frappe_whatsapp/tests/fixtures/bsuid/` for
phone-plus-BSUID, BSUID-only, parent-ID, rotation, statuses, and
contact-request scenarios.

### Messaging and status

- [ ] Phone-only, BSUID-only, and both-destination sends work.
- [ ] Phone wins when both `to` and `recipient` are supplied.
- [ ] Authentication templates reject BSUID-only delivery before Meta.
- [ ] A timeout replay uses the same external reference and does not resend.
- [ ] Provider and local Frappe message IDs are persisted.
- [ ] Statuses match without a phone and do not regress out of order.
- [ ] Duplicate and concurrent status events are idempotent.

### Calling and UI

- [ ] State, permission, and start calls work with phone and BSUID identities.
- [ ] Permission and call idempotency keys survive uncertain retries.
- [ ] The approved staged regular-BSUID call rings through the PBX route.
- [ ] A numeric WhatsApp call proves the existing route is unchanged.
- [ ] Phone-optional leads render, message, and call without misleading labels.

### Direct webhook phase

- [ ] Valid signatures succeed using the exact raw body.
- [ ] Wrong app IDs, signatures, and expired timestamps fail.
- [ ] Event ID/header mismatches and changed-payload collisions fail closed.
- [ ] Duplicate events return the previous committed outcome.
- [ ] 429/5xx retry behavior and terminal 4xx handling are verified.
- [ ] URL cutover and rollback do not create duplicate CRM records.

BSUID production delivery is ready only after phase-one CRM acceptance passes.
Direct CRM delivery is a separate later acceptance gate.
