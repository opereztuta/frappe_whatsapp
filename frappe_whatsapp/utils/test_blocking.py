from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias, cast
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp.utils.blocking import (
    MetaBlockRequestError,
    block_contact,
    is_contact_blocked,
    unblock_contact,
)
from frappe_whatsapp.frappe_whatsapp.api.blocking import (
    block_profile_contact,
    get_profile_block_state,
    unblock_profile_contact,
)
from frappe_whatsapp.utils.webhook import (
    _process_incoming_message,
    download_and_attach_media,
)

if TYPE_CHECKING:
    WhatsAppAccount: TypeAlias = Any
    WhatsAppBlockedContact: TypeAlias = Any
    WhatsAppMessage: TypeAlias = Any
    WhatsAppProfiles: TypeAlias = Any


class TestBlockedIncomingContacts(FrappeTestCase):
    def setUp(self):
        frappe.reload_doc(
            "frappe_whatsapp",
            "doctype",
            "whatsapp_blocked_contact",
        )
        frappe.reload_doc("frappe_whatsapp", "doctype", "whatsapp_profiles")
        frappe.reload_doc("frappe_whatsapp", "doctype", "whatsapp_message")

    def _create_account(self) -> WhatsAppAccount:
        suffix = frappe.generate_hash(length=8)
        return cast("WhatsAppAccount", frappe.get_doc({
            "doctype": "WhatsApp Account",
            "account_name": f"Block Test Account {suffix}",
            "status": "Active",
            "url": "https://graph.facebook.com",
            "version": "v25.0",
            "phone_id": f"phone-{suffix}",
        }).insert(ignore_permissions=True))

    def _create_profile(
            self, *, whatsapp_account: str | None = None,
            number: str | None = None) -> WhatsAppProfiles:
        suffix = frappe.generate_hash(length=8)
        return cast("WhatsAppProfiles", frappe.get_doc({
            "doctype": "WhatsApp Profiles",
            "profile_name": f"Block Test Profile {suffix}",
            "number": number or f"+1555{suffix}",
            "whatsapp_account": whatsapp_account,
        }).insert(ignore_permissions=True))

    def test_local_block_prevents_incoming_media_insert_and_download(self):
        account = self._create_account()
        contact_number = "+15551234567"
        message_id = f"wamid.{frappe.generate_hash(length=8)}"

        result = block_contact(
            whatsapp_account=str(account.name),
            contact_number=contact_number,
            reason="Spam",
            sync_meta=False,
        )

        self.assertTrue(result["local_blocked"])
        self.assertTrue(is_contact_blocked(
            whatsapp_account=str(account.name),
            contact_number=contact_number,
        ))

        with (
            patch("frappe_whatsapp.utils.webhook.frappe.enqueue") as enqueue,
            patch(
                "frappe_whatsapp.utils.webhook"
                ".forward_incoming_to_app_async"
            ) as forward_async,
        ):
            _process_incoming_message(
                message={
                    "id": message_id,
                    "from": contact_number,
                    "type": "document",
                    "document": {
                        "id": "media-spam",
                        "mime_type": "application/pdf",
                    },
                },
                whatsapp_account=account,
                sender_profile_name="Spam Sender",
            )

        self.assertFalse(frappe.db.exists(
            "WhatsApp Message",
            {"message_id": message_id},
        ))
        enqueue.assert_not_called()
        forward_async.assert_not_called()

    def test_media_download_skips_if_contact_blocked_after_stub_insert(self):
        account = self._create_account()
        contact_number = "+15557654321"
        message = cast("WhatsAppMessage", frappe.get_doc({
            "doctype": "WhatsApp Message",
            "type": "Incoming",
            "from": contact_number,
            "message": "",
            "message_id": f"wamid.{frappe.generate_hash(length=8)}",
            "content_type": "image",
            "whatsapp_account": str(account.name),
        }).insert(ignore_permissions=True))

        block_contact(
            whatsapp_account=str(account.name),
            contact_number=contact_number,
            reason="Queued media blocked",
            sync_meta=False,
        )

        with (
            patch(
                "frappe_whatsapp.utils.webhook.requests.get"
            ) as requests_get,
            patch(
                "frappe_whatsapp.utils.webhook"
                ".forward_incoming_to_app_async"
            ) as forward_async,
        ):
            download_and_attach_media(
                whatsapp_account_name=str(account.name),
                message_docname=str(message.name),
                media_id="media-queued",
                message_type="image",
            )

        requests_get.assert_not_called()
        forward_async.assert_not_called()

    def test_unblock_contact_allows_inbound_guard_to_pass(self):
        account = self._create_account()
        contact_number = "+15559876543"

        block_contact(
            whatsapp_account=str(account.name),
            contact_number=contact_number,
            sync_meta=False,
        )
        unblock_contact(
            whatsapp_account=str(account.name),
            contact_number=contact_number,
            sync_meta=False,
        )

        self.assertFalse(is_contact_blocked(
            whatsapp_account=str(account.name),
            contact_number=contact_number,
        ))

    @patch("frappe_whatsapp.utils.blocking._call_meta_block_users")
    def test_block_contact_records_meta_success(self, mock_meta_block):
        account = self._create_account()
        mock_meta_block.return_value = {
            "messaging_product": "whatsapp",
            "block_users": {
                "added_users": [
                    {"input": "+15550001111", "wa_id": "15550001111"}
                ]
            },
        }

        result = block_contact(
            whatsapp_account=str(account.name),
            contact_number="+15550001111",
            reason="Spam",
            sync_meta=True,
        )

        self.assertTrue(result["meta"]["ok"])
        doc = cast(
            "WhatsAppBlockedContact",
            frappe.get_doc("WhatsApp Blocked Contact", result["name"]),
        )
        self.assertEqual(doc.meta_status, "Blocked")
        self.assertEqual(doc.meta_input, "+15550001111")
        self.assertEqual(doc.meta_wa_id, "15550001111")

    @patch("frappe_whatsapp.utils.blocking._call_meta_block_users")
    def test_meta_failure_keeps_local_block_active(self, mock_meta_block):
        account = self._create_account()
        mock_meta_block.side_effect = MetaBlockRequestError(
            "(#139100) Failed to block users",
            payload={
                "error": {
                    "code": 139100,
                    "message": "Failed to block users",
                }
            },
        )

        result = block_contact(
            whatsapp_account=str(account.name),
            contact_number="+15552223333",
            reason="Spam",
            sync_meta=True,
        )

        self.assertFalse(result["meta"]["ok"])
        self.assertTrue(is_contact_blocked(
            whatsapp_account=str(account.name),
            contact_number="+15552223333",
        ))
        doc = cast(
            "WhatsAppBlockedContact",
            frappe.get_doc("WhatsApp Blocked Contact", result["name"]),
        )
        self.assertEqual(doc.meta_status, "Failed")
        self.assertIn("139100", str(doc.last_error_payload))

    def test_profile_block_state_requires_account_when_profile_has_none(self):
        profile = self._create_profile()

        state = get_profile_block_state(profile_name=str(profile.name))

        self.assertTrue(state["requires_whatsapp_account"])
        self.assertFalse(state["is_blocked"])
        self.assertEqual(state["contact_number"], str(profile.number))

    def test_profile_block_and_unblock_wrappers(self):
        account = self._create_account()
        profile = self._create_profile(whatsapp_account=str(account.name))

        block_result = block_profile_contact(
            profile_name=str(profile.name),
            reason="Spam",
            sync_meta=False,
        )

        self.assertTrue(block_result["local_blocked"])
        blocked_state = get_profile_block_state(
            profile_name=str(profile.name))
        self.assertTrue(blocked_state["is_blocked"])
        self.assertEqual(
            blocked_state["block_record"]["whatsapp_account"],
            str(account.name),
        )

        unblock_result = unblock_profile_contact(
            profile_name=str(profile.name),
            reason="Mistake",
            sync_meta=False,
        )

        self.assertFalse(unblock_result["local_blocked"])
        unblocked_state = get_profile_block_state(
            profile_name=str(profile.name))
        self.assertFalse(unblocked_state["is_blocked"])
