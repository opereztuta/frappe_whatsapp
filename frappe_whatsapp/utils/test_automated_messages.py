"""Classify structured permission summaries without inspecting display text."""

from typing import Any, cast
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import WhatsAppMessage
from frappe_whatsapp.utils.routing import serialize_incoming_message_for_forwarding
from frappe_whatsapp.utils.webhook import _handle_interactive


class TestAutomatedPermissionMessages(TestCase):
    def _handle(self, interactive: dict[str, Any], *, phone: str = ""):
        saved: dict[str, Any] = {}

        def create(values):
            saved.update(values)
            doc = frappe._dict({**values, "name": "synthetic-permission-message", "creation": "2026-10-14 12:00:00"})
            doc.insert = Mock(return_value=doc)
            return doc

        with (
            patch("frappe_whatsapp.utils.webhook.frappe.get_doc", side_effect=create),
            patch("frappe_whatsapp.utils.calling.handle_call_permission_reply") as permission,
            patch("frappe_whatsapp.utils.webhook.forward_incoming_to_app_async") as forward,
            patch("frappe_whatsapp.utils.webhook._handle_consent_keywords"),
            patch("frappe_whatsapp.utils.webhook._enqueue_language_detection"),
        ):
            _handle_interactive(
                message={"id": "synthetic-message-id", "from": phone, "interactive": interactive},
                whatsapp_account=frappe._dict(name="synthetic-account"),
                sender_profile_name="Synthetic User", routed_app="synthetic-app",
                reply_to_message_id="synthetic-context", is_reply=True,
                identity_fields={"from": phone, "from_user_id": "US.SyntheticPermission"},
            )
        return saved, permission, forward

    def _serialize(self, values):
        doc = cast(WhatsAppMessage, frappe._dict({
            "name": "synthetic-message", "creation": "2026-10-14 12:00:00",
            "message_id": "synthetic-id", "whatsapp_account": "synthetic-account",
            **values,
        }))
        return serialize_incoming_message_for_forwarding(incoming_message_doc=doc)

    def test_permission_responses_are_automated_and_forwarded(self):
        for response, permanent, phone in [("accept", 0, ""), ("accept", 1, "15551234567"), ("reject", 0, "")]:
            with self.subTest(response=response, permanent=permanent, phone=phone):
                saved, permission, forward = self._handle({
                    "type": "call_permission_reply",
                    "call_permission_reply": {"response": response, "is_permanent": permanent},
                }, phone=phone)
                self.assertEqual(saved["is_automated_message"], 1)
                self.assertEqual(saved["message"], "Call permission accepted" if response == "accept" else "Call permission rejected")
                self.assertEqual(saved["message_id"], "synthetic-message-id")
                self.assertEqual(permission.call_args.kwargs["response"], response)
                self.assertEqual(permission.call_args.kwargs["is_permanent"], bool(permanent))
                forward.assert_called_once_with(incoming_message_name="synthetic-permission-message")
                payload = self._serialize(saved)
                self.assertIs(payload["is_automated_message"], True)
                self.assertEqual(payload["from_user_id"], "US.SyntheticPermission")

    def test_user_button_and_list_replies_are_not_automated(self):
        for kind in ["button_reply", "list_reply"]:
            with self.subTest(kind=kind):
                saved, permission, forward = self._handle({
                    "type": kind, kind: {"id": "Call permission accepted", "title": "Call permission accepted"},
                })
                self.assertNotIn("is_automated_message", saved)
                self.assertIs(self._serialize(saved)["is_automated_message"], False)
                permission.assert_not_called()
                forward.assert_called_once()

    def test_user_text_and_legacy_messages_default_false(self):
        for text in ["Call permission accepted", "Call permission rejected", "Hello"]:
            with self.subTest(text=text):
                self.assertIs(self._serialize({"message": text, "content_type": "text"})["is_automated_message"], False)

    def test_check_field_zero_serializes_as_boolean_false(self):
        self.assertIs(self._serialize({"content_type": "button", "is_automated_message": 0})["is_automated_message"], False)

    def test_failed_permission_handling_does_not_enqueue_immediately(self):
        doc = Mock(name="permission-document")
        doc.name = "synthetic-message"
        doc.insert.return_value = doc
        with (
            patch("frappe_whatsapp.utils.webhook.frappe.get_doc", return_value=doc),
            patch("frappe_whatsapp.utils.calling.handle_call_permission_reply", side_effect=RuntimeError("permission failure")),
            patch("frappe_whatsapp.utils.webhook.forward_incoming_to_app_async") as forward,
        ):
            with self.assertRaises(RuntimeError):
                _handle_interactive(
                    message={"interactive": {"type": "call_permission_reply", "call_permission_reply": {"response": "accept"}}},
                    whatsapp_account=frappe._dict(name="synthetic-account"),
                    sender_profile_name=None, routed_app=None, reply_to_message_id=None,
                    is_reply=False, identity_fields={},
                )
        forward.assert_not_called()
