"""Click-to-WhatsApp referral capture and Meta campaign resolution."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterator, TypedDict, cast

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_account.whatsapp_account import (
    WhatsAppAccount,
)
from frappe_whatsapp.utils.meta import request_meta_json


ATTRIBUTION_CACHE_DOCTYPE = "WhatsApp Ad Attribution"
MESSAGE_DOCTYPE = "WhatsApp Message"
NOTIFICATION_LOG_DOCTYPE = "WhatsApp Notification Log"
GRAPH_LOOKUP_TIMEOUT = 10
ATTRIBUTION_MESSAGE_FIELDS = frozenset({
    "referral_source_type", "referral_source_id", "referral_ctwa_clid",
    "referral_payload", "meta_ad_name", "meta_ad_account_id",
    "meta_adset_id", "meta_adset_name", "meta_campaign_id",
    "meta_campaign_name", "attribution_status", "attribution_resolved_at",
    "attribution_error",
})


class ReferralEvent(TypedDict):
    message_id: str
    referral: dict[str, Any]


def _bounded_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized[:limit] or None


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_referral(referral: Any) -> dict[str, Any]:
    """Return safe WhatsApp Message fields for a Meta referral object."""
    if not isinstance(referral, dict) or not referral:
        return {}

    source_type = _bounded_text(referral.get("source_type"), 20)
    source_id = _bounded_text(referral.get("source_id"), 64)
    status = (
        "Pending"
        if source_type == "ad" and source_id
        else "Not Applicable"
    )
    return {
        "referral_source_type": source_type,
        "referral_source_id": source_id,
        "referral_ctwa_clid": _bounded_text(
            referral.get("ctwa_clid"), 500),
        "referral_payload": json.dumps(
            referral,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ),
        "attribution_status": status,
    }


def _cache_name(whatsapp_account: str, ad_id: str) -> str:
    value = f"{whatsapp_account}\0{ad_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _message_attribution_values(cache: Any) -> dict[str, Any]:
    return {
        "meta_ad_name": cache.get("ad_name"),
        "meta_ad_account_id": cache.get("ad_account_id"),
        "meta_adset_id": cache.get("adset_id"),
        "meta_adset_name": cache.get("adset_name"),
        "meta_campaign_id": cache.get("campaign_id"),
        "meta_campaign_name": cache.get("campaign_name"),
        "attribution_status": "Resolved",
        "attribution_resolved_at": cache.get("resolved_at") or now_datetime(),
        "attribution_error": None,
    }


def _set_message_values(message_doc: Any, values: dict[str, Any]) -> None:
    if not values:
        return
    frappe.db.set_value(
        MESSAGE_DOCTYPE,
        message_doc.name,
        values,
        update_modified=False,
    )
    for fieldname, value in values.items():
        message_doc.set(fieldname, value)


def _store_cache(
    *, whatsapp_account: str, ad_id: str, payload: dict[str, Any]
) -> Any:
    adset = payload.get("adset")
    campaign = payload.get("campaign")
    adset = adset if isinstance(adset, dict) else {}
    campaign = campaign if isinstance(campaign, dict) else {}
    resolved_at = now_datetime()
    cache_name = _cache_name(whatsapp_account, ad_id)
    values: dict[str, Any] = {
        "doctype": ATTRIBUTION_CACHE_DOCTYPE,
        "name": cache_name,
        "cache_key": cache_name,
        "whatsapp_account": whatsapp_account,
        "ad_id": ad_id,
        "ad_name": _bounded_text(payload.get("name"), 500),
        "ad_account_id": _bounded_text(payload.get("account_id"), 64),
        "adset_id": _bounded_text(adset.get("id"), 64),
        "adset_name": _bounded_text(adset.get("name"), 500),
        "campaign_id": _bounded_text(campaign.get("id"), 64),
        "campaign_name": _bounded_text(campaign.get("name"), 500),
        "effective_status": _bounded_text(
            payload.get("effective_status"), 50),
        "resolved_at": resolved_at,
    }
    existing = frappe.db.exists(ATTRIBUTION_CACHE_DOCTYPE, cache_name)
    if existing:
        existing_name = str(existing)
        frappe.db.set_value(
            ATTRIBUTION_CACHE_DOCTYPE,
            existing_name,
            {key: value for key, value in values.items()
             if key not in {"doctype", "name", "cache_key"}},
            update_modified=False,
        )
        return frappe.get_doc(ATTRIBUTION_CACHE_DOCTYPE, existing_name)

    try:
        return frappe.get_doc(values).insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        return frappe.get_doc(ATTRIBUTION_CACHE_DOCTYPE, cache_name)


def _resolve_ad(*, account: WhatsAppAccount, ad_id: str) -> Any:
    token = account.get_password("ads_access_token")
    if not token:
        raise frappe.ValidationError(
            _(
                "Campaign tracking is enabled but no Ads access token "
                "is configured."
            )
        )

    base_url = f"{str(account.url).rstrip('/')}/{str(account.version).strip('/')}"
    payload = request_meta_json(
        "GET",
        f"{base_url}/{ad_id}",
        account_name=str(account.name),
        operation=_("campaign attribution lookup"),
        headers={"Authorization": f"Bearer {token}"},
        params={
            "fields": (
                "id,name,account_id,effective_status,"
                "adset{id,name},campaign{id,name}"
            )
        },
        timeout=GRAPH_LOOKUP_TIMEOUT,
    )
    if str(payload.get("id") or "") != ad_id:
        raise frappe.ValidationError(
            _("Meta returned an invalid ad attribution response."))
    campaign = payload.get("campaign")
    if not isinstance(campaign, dict) or not campaign.get("id"):
        raise frappe.ValidationError(
            _("Meta did not return a campaign for this ad."))
    return _store_cache(
        whatsapp_account=str(account.name), ad_id=ad_id, payload=payload)


def resolve_message_attribution(message_doc: Any) -> None:
    """Best-effort enrichment. Failure must never block message delivery."""
    source_type = str(message_doc.get("referral_source_type") or "")
    ad_id = str(message_doc.get("referral_source_id") or "")
    if not message_doc.get("referral_payload"):
        return
    # A code deployment can precede schema migration. Retained webhook logs
    # remain the source for a later backfill; do not block ordinary delivery.
    if not ATTRIBUTION_MESSAGE_FIELDS.issubset(
        frappe.db.get_table_columns(MESSAGE_DOCTYPE)
    ):
        return
    if source_type != "ad" or not ad_id:
        if message_doc.get("attribution_status") != "Not Applicable":
            _set_message_values(
                message_doc, {"attribution_status": "Not Applicable"})
        return

    cache_name = _cache_name(str(message_doc.whatsapp_account), ad_id)
    try:
        account_name = str(message_doc.whatsapp_account or "")
        account = cast(
            WhatsAppAccount,
            frappe.get_doc("WhatsApp Account", account_name),
        )
        if not cint(account.enable_campaign_tracking):
            raise frappe.ValidationError(
                _(
                    "Campaign tracking is not enabled for this "
                    "WhatsApp Account."
                )
            )
        cache = None
        if frappe.db.exists(ATTRIBUTION_CACHE_DOCTYPE, cache_name):
            cache = frappe.get_doc(ATTRIBUTION_CACHE_DOCTYPE, cache_name)
        if cache is None:
            cache = _resolve_ad(account=account, ad_id=ad_id)
        _set_message_values(
            message_doc, _message_attribution_values(cache))
    except (
        frappe.db.OperationalError, frappe.db.InternalError,
        frappe.db.ProgrammingError, frappe.db.DataError,
    ):
        # Connection failures, deadlocks and other database errors must reach
        # the worker's transaction/retry handling rather than become ad errors.
        raise
    except Exception as exc:
        error = _bounded_text(str(exc), 500) or type(exc).__name__
        _set_message_values(
            message_doc,
            {
                "attribution_status": "Failed",
                "attribution_error": error,
            },
        )
        frappe.logger("frappe_whatsapp").warning(
            "WhatsApp campaign attribution failed for message %s: %s",
            message_doc.name,
            error,
        )


def serialize_referral(message_doc: Any) -> dict[str, Any] | None:
    referral = _json_dict(message_doc.get("referral_payload"))
    if not referral and not message_doc.get("referral_source_id"):
        return None

    def object_or_none(identifier: Any, name: Any, **extra: Any):
        if not identifier and not name and not any(extra.values()):
            return None
        return {"id": identifier, "name": name, **extra}

    def safe(fieldname: str, limit: int = 2000) -> str | None:
        return _bounded_text(referral.get(fieldname), limit)

    return {
        "source_type": message_doc.get("referral_source_type")
        or safe("source_type", 20),
        "source_id": message_doc.get("referral_source_id")
        or safe("source_id", 64),
        "source_url": safe("source_url"),
        "ctwa_clid": message_doc.get("referral_ctwa_clid")
        or safe("ctwa_clid", 500),
        "headline": safe("headline", 500),
        "body": safe("body", 2000),
        "media_type": safe("media_type", 20),
        "image_url": safe("image_url"),
        "video_url": safe("video_url"),
        "thumbnail_url": safe("thumbnail_url"),
        "welcome_message": safe("welcome_message", 1000),
        "ad": object_or_none(
            message_doc.get("referral_source_id"),
            message_doc.get("meta_ad_name"),
            account_id=message_doc.get("meta_ad_account_id"),
        ) if message_doc.get("referral_source_type") == "ad" else None,
        "adset": object_or_none(
            message_doc.get("meta_adset_id"),
            message_doc.get("meta_adset_name"),
        ),
        "campaign": object_or_none(
            message_doc.get("meta_campaign_id"),
            message_doc.get("meta_campaign_name"),
        ),
        "resolution_status": str(
            message_doc.get("attribution_status") or "Not Applicable"
        ).lower().replace(" ", "_"),
    }


def iter_webhook_referrals(payload: Any) -> Iterator[ReferralEvent]:
    data = _json_dict(payload)
    raw_entries = data.get("entry")
    entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes") or []
        changes = changes if isinstance(changes, list) else [changes]
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            messages = value.get("messages") or []
            messages = messages if isinstance(messages, list) else [messages]
            for message in messages:
                if not isinstance(message, dict):
                    continue
                referral = message.get("referral")
                message_id = str(message.get("id") or "")
                if message_id and isinstance(referral, dict) and referral:
                    yield {"message_id": message_id, "referral": referral}


def _get_referral_log_rows() -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        frappe.db.sql(
            f"""
            SELECT meta_data
            FROM `tab{NOTIFICATION_LOG_DOCTYPE}`
            WHERE template = 'Webhook'
              AND meta_data LIKE %s
            ORDER BY creation
            """,
            ('%"referral"%',),
            as_dict=True,
        ),
    )


@frappe.whitelist()
def backfill_campaign_attribution(dry_run: bool = True) -> dict[str, int]:
    """Backfill retained referrals without replaying client webhooks."""
    frappe.only_for("System Manager")
    dry_run = bool(cint(dry_run))
    stats = {
        "scanned": 0,
        "matched": 0,
        "updated": 0,
        "skipped": 0,
        "unresolved": 0,
        "unique_ads": 0,
    }
    rows = _get_referral_log_rows()
    seen_messages: set[str] = set()
    updated_messages: set[str] = set()
    unique_ads: set[tuple[str, str]] = set()
    for row in rows:
        for event in iter_webhook_referrals(row.get("meta_data")):
            stats["scanned"] += 1
            if event["message_id"] in seen_messages:
                stats["skipped"] += 1
                continue
            seen_messages.add(event["message_id"])
            raw_message_name = frappe.db.get_value(
                MESSAGE_DOCTYPE,
                {"message_id": event["message_id"]},
                "name",
            )
            if not raw_message_name:
                stats["skipped"] += 1
                continue
            message_name = str(raw_message_name)
            stats["matched"] += 1
            values = normalize_referral(event["referral"])
            existing_rows = cast(
                list[dict[str, Any]],
                frappe.get_all(
                    MESSAGE_DOCTYPE,
                    filters={"name": message_name},
                    fields=["whatsapp_account", *values.keys()],
                    limit=1,
                ),
            )
            existing = existing_rows[0] if existing_rows else {}
            account_name = existing.get("whatsapp_account")
            if (
                values.get("referral_source_type") == "ad"
                and values.get("referral_source_id")
                and account_name
            ):
                unique_ads.add((
                    str(account_name), str(values["referral_source_id"])))
            if dry_run:
                continue
            changes = {
                fieldname: value
                for fieldname, value in values.items()
                if value is not None
                and existing
                and existing.get(fieldname) in (None, "")
            }
            if changes:
                frappe.db.set_value(
                    MESSAGE_DOCTYPE,
                    message_name,
                    changes,
                    update_modified=False,
                )
                updated_messages.add(str(message_name))
            message_doc = frappe.get_doc(MESSAGE_DOCTYPE, message_name)
            before_status = message_doc.get("attribution_status")
            if before_status != "Resolved":
                resolve_message_attribution(message_doc)
            if (
                before_status != "Resolved"
                and message_doc.get("attribution_status") == "Resolved"
            ):
                updated_messages.add(str(message_name))
            if message_doc.get("attribution_status") == "Failed":
                stats["unresolved"] += 1

    stats["unique_ads"] = len(unique_ads)
    stats["updated"] = len(updated_messages)
    return stats
