# Manual deployment: WhatsApp webhook reliability

Deploy the reviewed changes in both `frappe_whatsapp` and `zoni_edu` together.
No CRM service or `whatsapp_chat` deployment is required by this change.

## Before deployment

- Record the current commit in each production repository and the new reviewed
  commit to deploy. Confirm the working trees are clean.
- Back up `careers.zoni.edu` using `bench --site careers.zoni.edu backup`.
- Arrange a maintenance window that stops new web requests and quiesces workers
  before changing code. Account for queued webhook jobs; do not purge queues or
  bulk-retry historical failures.
- Run regression tests on an isolated site with external HTTP, email and job
  execution mocked. Relevant modules are `frappe_whatsapp.utils.test_routing`,
  `test_campaign_attribution`, `test_webhook_template_sync` and
  `test_webhook_signature`; in `zoni_edu`, run
  `zoni_edu.zoni_edu.utils.test_whatsapp_profile_retry`, the profile/consent tests
  in `zoni_edu.zoni_edu.doctype.contacts.test_contacts`, and
  `zoni_edu.zoni_edu.integrations.whatsapp.test_webhook`.

## Deploy and validate

1. Deploy the recorded, reviewed revisions to both repositories using the
   existing manual deployment process. Keep requests and workers quiesced.
2. From the production bench, run:

   ```bash
   bench --site careers.zoni.edu migrate
   bench --site careers.zoni.edu clear-cache
   ```

3. Verify that `WhatsApp Message` has all fields listed in
   `campaign_attribution.ATTRIBUTION_MESSAGE_FIELDS`, that `WhatsApp Ad
   Attribution` exists, and that the active accounts still have campaign
   tracking and their Ads tokens configured. Verify schema through database
   columns, not only DocType metadata. Do not print tokens.
4. Restart the bench processes with `bench restart` and resume requests and
   workers. Restarting also removes stale worker code and schema caches.
5. Verify a normal text reaches Frappe and the correct CRM channel once. For a
   new ad-originated message, verify the campaign referral reaches the CRM's
   per-message JSON. Verify organic and failed-resolution messages still
   forward. Use designated test contacts for any active smoke tests.
6. Confirm a trusted template update completes its background synchronization.
   The public template-fetch endpoint must remain restricted. New sync jobs
   target `frappe_whatsapp.utils.webhook._sync_templates_from_webhook`.
   Previously queued jobs targeting `fetch` still retain their old Guest user;
   do not bulk-retry those jobs. A subsequent trusted event or an authorized
   manual template fetch performs a fresh synchronization.
7. Monitor Error Log and worker logs for `system` Select validation errors,
   missing attribution columns, template permission failures and exhausted
   profile retries. System events should generate bounded diagnostic warnings
   without creating messages or changing identities. Profile timestamp
   conflicts should roll back and retry through Frappe's bounded worker logic.

## Attribution audit and conditional backfill

The read-only production audit on 2026-09-08 found 3,188 retained referral
events representing 3,118 unique, existing messages. All 2,774 referrals
explicitly marked as ads had resolved campaign IDs. The other 344 retained
their raw referrals but lacked an ad ID or source type and were classified as
Not Applicable. **No backfill was needed at that snapshot.** Do not infer ad
identities from URLs or reclassify those incomplete referrals automatically.

Repeat the completeness audit after deployment: deduplicate retained Webhook
notification-log referrals by message ID, match existing incoming messages,
and count explicit ad referrals with missing raw referral data, a non-Resolved
status or a missing campaign ID. Check unmatched messages separately.

If new attribution gaps are found, preview the existing command first:

```bash
bench --site careers.zoni.edu execute \
  frappe_whatsapp.utils.campaign_attribution.backfill_campaign_attribution \
  --kwargs '{"dry_run": true}'
```

The preview's `matched` count is not the number needing repair; it includes
already resolved messages. Its `updated` count remains zero in dry-run mode.
Compare the preview with the field-level completeness audit. After reviewing
the scope, apply manually only when gaps require it:

```bash
bench --site careers.zoni.edu execute \
  frappe_whatsapp.utils.campaign_attribution.backfill_campaign_attribution \
  --kwargs '{"dry_run": false}'
```

Verify complete attribution, unchanged message `modified` timestamps, and no
client webhook delivery. This command updates Frappe only; it does not repair
historical CRM attribution or recreate absent messages. Preserve existing
resolved fields and do not replay historical webhook payloads.

The ordinary text messages associated with Error Logs `fhbfeqk636` and
`feui6e01iq` were absent from Frappe at the audit. Their recovery is separate
from this attribution task and must not be attempted through this backfill.

## Rollback

If validation fails, quiesce processing and restore the recorded previous
application revisions. Retain the additive attribution schema, clear caches,
and restart before resuming. The new private template worker will not exist
in the old revision: record and cancel only pending jobs targeting that new
worker before reverting, then use an authorized manual template fetch if
needed. Do not purge or replay incoming-message queues.
