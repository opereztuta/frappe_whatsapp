import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp.utils.routing import (
    forward_incoming_to_app,
    serialize_incoming_message_for_forwarding,
)


class TestRouting(FrappeTestCase):
    def test_serialize_incoming_message_for_forwarding_includes_profile_name(
        self,
    ):
        incoming_message_doc = frappe._dict(
            {
                "name": "MSG-0001",
                "doctype": "WhatsApp Message",
                "from": "15551234567",
                "to": "15557654321",
                "profile_name": "Jane Sender",
                "whatsapp_account": "Test Account",
                "content_type": "text",
                "message": "Hello there",
                "message_id": "wamid.123",
                "creation": "2026-03-17 10:00:00",
                "attach": None,
            }
        )

        payload = serialize_incoming_message_for_forwarding(
            incoming_message_doc=incoming_message_doc
        )

        self.assertEqual(payload["profile_name"], "Jane Sender")

    @patch("frappe_whatsapp.utils.routing._mark_incoming_message_forwarded")
    @patch("frappe_whatsapp.utils.routing.make_post_request")
    @patch(
        "frappe_whatsapp.utils.routing._incoming_message_already_forwarded",
        return_value=False,
    )
    @patch("frappe_whatsapp.utils.routing.frappe.get_doc")
    def test_forward_incoming_to_app_posts_profile_name_in_payload(
        self,
        mock_get_doc,
        _mock_already_forwarded,
        mock_make_post_request,
        _mock_mark_forwarded,
    ):
        mock_get_doc.return_value = frappe._dict(
            {
                "enabled": 1,
                "inbound_webhook_url": "https://example.com/incoming",
                "app_id": "client-app-1",
            }
        )
        incoming_message_doc = frappe._dict(
            {
                "name": "MSG-0001",
                "doctype": "WhatsApp Message",
                "routed_app": "Test Client App",
                "from": "15551234567",
                "to": "15557654321",
                "profile_name": "Jane Sender",
                "whatsapp_account": "Test Account",
                "content_type": "text",
                "message": "Hello there",
                "message_id": "wamid.123",
                "creation": "2026-03-17 10:00:00",
                "attach": None,
            }
        )

        forward_incoming_to_app(incoming_message_doc=incoming_message_doc)

        self.assertTrue(mock_make_post_request.called)
        payload = json.loads(mock_make_post_request.call_args.kwargs["data"])
        self.assertEqual(payload["event"], "whatsapp.incoming")
        self.assertEqual(payload["message"]["profile_name"], "Jane Sender")
