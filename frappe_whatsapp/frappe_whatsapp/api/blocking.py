from __future__ import annotations

from typing import Any, cast

import frappe
from frappe import _

from frappe_whatsapp.utils.blocking import (
    BLOCKED_CONTACT_DOCTYPE,
    block_contact as _block_contact,
    list_local_blocked_contacts,
    list_meta_blocked_contacts,
    unblock_contact as _unblock_contact,
)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _require_block_permission() -> None:
    if (
        not frappe.has_permission(BLOCKED_CONTACT_DOCTYPE, "write")
        and not frappe.has_permission(BLOCKED_CONTACT_DOCTYPE, "create")
    ):
        frappe.throw(
            _("Not permitted to manage WhatsApp blocked contacts."),
            frappe.PermissionError,
        )


def _resolve_from_message(
        *, message_name: str | None,
        contact_number: str | None,
        whatsapp_account: str | None,
        source_app: str | None) -> tuple[str, str, str | None]:
    if not message_name:
        if not (contact_number and whatsapp_account):
            frappe.throw(
                _("Provide either message_name or both contact_number "
                  "and whatsapp_account."))
        return str(contact_number), str(whatsapp_account), source_app

    from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import WhatsAppMessage  # noqa: E501

    message = cast(WhatsAppMessage,
                   frappe.get_doc("WhatsApp Message", message_name))
    resolved_number = contact_number or message.get("from") or message.to
    resolved_account = whatsapp_account or message.whatsapp_account
    resolved_app = (
        source_app
        or cast(str | None, message.get("routed_app"))
        or cast(str | None, message.get("source_app"))
    )
    if not (resolved_number and resolved_account):
        frappe.throw(
            _("Could not resolve contact number and WhatsApp Account "
              "from message."))
    return str(resolved_number), str(resolved_account), resolved_app


@frappe.whitelist()
def block_contact(
    contact_number: str | None = None,
    whatsapp_account: str | None = None,
    message_name: str | None = None,
    reason: str | None = None,
    source_app: str | None = None,
    sync_meta: int | str | bool = 1,
):
    """Block a WhatsApp contact locally and best-effort at Meta.

    Intended for authenticated clients such as Zoni CRM.  Passing
    ``message_name`` is the most reliable call shape because it lets this app
    resolve both the sender number and the WhatsApp Account from the inbound
    message Zoni already received.
    """
    _require_block_permission()
    number, account, resolved_app = _resolve_from_message(
        message_name=message_name,
        contact_number=contact_number,
        whatsapp_account=whatsapp_account,
        source_app=source_app,
    )
    return _block_contact(
        whatsapp_account=account,
        contact_number=number,
        reason=reason,
        source_app=resolved_app,
        source_message=message_name,
        sync_meta=_truthy(sync_meta),
    )


@frappe.whitelist()
def unblock_contact(
    contact_number: str | None = None,
    whatsapp_account: str | None = None,
    message_name: str | None = None,
    reason: str | None = None,
    source_app: str | None = None,
    sync_meta: int | str | bool = 1,
):
    _require_block_permission()
    number, account, resolved_app = _resolve_from_message(
        message_name=message_name,
        contact_number=contact_number,
        whatsapp_account=whatsapp_account,
        source_app=source_app,
    )
    return _unblock_contact(
        whatsapp_account=account,
        contact_number=number,
        reason=reason,
        source_app=resolved_app,
        source_message=message_name,
        sync_meta=_truthy(sync_meta),
    )


@frappe.whitelist()
def get_blocked_contacts(
        whatsapp_account: str | None = None,
        sync_meta: int | str | bool = 0,
        limit: int | str = 100):
    _require_block_permission()
    local = list_local_blocked_contacts(
        whatsapp_account=whatsapp_account,
        limit=int(limit or 100),
    )
    meta = None
    if _truthy(sync_meta):
        if not whatsapp_account:
            frappe.throw(
                _("whatsapp_account is required when sync_meta is enabled."))
        assert whatsapp_account is not None
        meta = list_meta_blocked_contacts(
            whatsapp_account=whatsapp_account,
            limit=int(limit or 100),
        )
    return {"local": local, "meta": meta}
