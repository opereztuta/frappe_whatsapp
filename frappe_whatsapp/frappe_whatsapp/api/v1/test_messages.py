from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp.frappe_whatsapp.api.v1.messages import send


class TestVersionedMessagesAPI(FrappeTestCase):
    def _account(self):
        suffix = frappe.generate_hash(length=8)
        return frappe.get_doc({
            "doctype": "WhatsApp Account",
            "account_name": f"API Test Account {suffix}",
            "status": "Active",
            "token": "test-token",
            "url": "https://graph.facebook.com",
            "version": "v24.0",
            "phone_id": f"api-phone-{suffix}",
        }).insert(ignore_permissions=True)

    def _app(self, account):
        suffix = frappe.generate_hash(length=8)
        return frappe.get_doc({
            "doctype": "WhatsApp Client App",
            "app_id": f"api-client-{suffix}",
            "enabled": 1,
            "api_user": frappe.session.user,
            "allowed_accounts": [{"whatsapp_account": account.name}],
        }).insert(ignore_permissions=True)

    def test_send_is_idempotent_and_phone_takes_precedence(self):
        account = self._account()
        app = self._app(account)
        external_reference = f"crm-{frappe.generate_hash(length=12)}"

        with patch(
            "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message."
            "whatsapp_message.get_service_window_status",
            return_value=(True, ""),
        ), patch(
            "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message."
            "whatsapp_message.WhatsAppMessage._check_consent",
        ), patch(
            "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message."
            "whatsapp_message.request_meta_json",
            return_value={"messages": [{"id": "wamid.api-test"}]},
        ) as mock_meta:
            first = send(
                external_reference=external_reference,
                content_type="text",
                to="+16505551234",
                recipient="US.13491208655302741918",
                whatsapp_account=account.name,
                source_app=app.name,
                message="hello",
            )
            replay = send(
                external_reference=external_reference,
                content_type="text",
                to="+16505551234",
                recipient="US.13491208655302741918",
                whatsapp_account=account.name,
                source_app=app.name,
                message="ignored duplicate",
            )

        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["message_name"], replay["message_name"])
        self.assertEqual(first["provider_message_id"], "wamid.api-test")
        self.assertEqual(first["recipient_type"], "phone")
        self.assertEqual(first["recipient"], "+16505551234")
        self.assertEqual(mock_meta.call_count, 1)
        meta_payload = mock_meta.call_args.kwargs["json_body"]
        self.assertEqual(meta_payload["to"], "16505551234")
        self.assertNotIn("recipient", meta_payload)
        self.assertEqual(
            frappe.db.count(
                "WhatsApp Message",
                {
                    "source_app": app.name,
                    "whatsapp_account": account.name,
                    "external_reference": external_reference,
                },
            ),
            1,
        )

    def test_disallowed_account_is_rejected_before_meta(self):
        allowed_account = self._account()
        disallowed_account = self._account()
        app = self._app(allowed_account)

        with patch(
            "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message."
            "whatsapp_message.request_meta_json",
        ) as mock_meta:
            with self.assertRaises(frappe.PermissionError):
                send(
                    external_reference=frappe.generate_hash(length=12),
                    content_type="text",
                    recipient="US.13491208655302741918",
                    whatsapp_account=disallowed_account.name,
                    source_app=app.name,
                    message="hello",
                )

        mock_meta.assert_not_called()
