import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp.utils.campaign_attribution import (
    backfill_campaign_attribution,
    iter_webhook_referrals,
    normalize_referral,
    resolve_message_attribution,
    serialize_referral,
)
from frappe_whatsapp.utils.routing import forward_incoming_to_app_by_name


_MOD = "frappe_whatsapp.utils.campaign_attribution"


def _referral() -> dict:
    return {
        "source_url": "https://fb.me/ad",
        "source_id": "120249647384630076",
        "source_type": "ad",
        "body": "Study English in New York",
        "headline": "Learn English",
        "media_type": "video",
        "video_url": "https://cdn.example.com/ad.mp4",
        "thumbnail_url": "https://cdn.example.com/thumb.jpg",
        "ctwa_clid": "click-id",
        "welcome_message": "Hello",
    }


def _graph_payload() -> dict:
    return {
        "id": "120249647384630076",
        "name": "NY English Ad",
        "account_id": "act-123",
        "effective_status": "ACTIVE",
        "adset": {"id": "adset-123", "name": "New York prospects"},
        "campaign": {"id": "campaign-123", "name": "Fall enrollment"},
    }


class TestCampaignAttribution(FrappeTestCase):
    def _account(self):
        suffix = frappe.generate_hash(length=8)
        return frappe.get_doc({
            "doctype": "WhatsApp Account",
            "account_name": f"Attribution Account {suffix}",
            "status": "Active",
            "url": "https://graph.facebook.com",
            "version": "v24.0",
            "enable_campaign_tracking": 1,
            "ads_access_token": "secret-ads-token",
        }).insert(ignore_permissions=True)

    def _message(self, account, *, message_id=None, referral=None):
        values = {
            "doctype": "WhatsApp Message",
            "type": "Incoming",
            "from": "15551234567",
            "message": "Hello",
            "message_id": message_id or f"wamid.{frappe.generate_hash(length=12)}",
            "content_type": "text",
            "whatsapp_account": account.name,
        }
        if referral is not None:
            values.update(normalize_referral(referral))
        return frappe.get_doc(values).insert(ignore_permissions=True)

    def _client_app(self):
        suffix = frappe.generate_hash(length=8)
        return frappe.get_doc({
            "doctype": "WhatsApp Client App",
            "app_id": f"attribution-client-{suffix}",
            "enabled": 1,
            "inbound_webhook_url": "https://example.com/whatsapp/inbound",
        }).insert(ignore_permissions=True)

    def test_normalize_complete_partial_and_removed_referral(self):
        values = normalize_referral(_referral())
        self.assertEqual(values["referral_source_type"], "ad")
        self.assertEqual(values["referral_source_id"], "120249647384630076")
        self.assertEqual(values["referral_ctwa_clid"], "click-id")
        self.assertEqual(values["attribution_status"], "Pending")
        self.assertEqual(
            json.loads(values["referral_payload"])["headline"],
            "Learn English",
        )

        partial = normalize_referral({"source_url": "https://fb.me/post"})
        self.assertEqual(partial["attribution_status"], "Not Applicable")
        self.assertIsNone(partial["referral_source_id"])
        self.assertEqual(normalize_referral(None), {})
        self.assertEqual(normalize_referral("removed"), {})

    def test_iter_webhook_referrals_supports_list_and_dict_entries(self):
        message = {"id": "wamid.referral", "referral": _referral()}
        payload = {
            "entry": [{"changes": [{"value": {"messages": [message]}}]}]
        }
        events = list(iter_webhook_referrals(payload))
        self.assertEqual(events[0]["message_id"], "wamid.referral")

        payload["entry"] = payload["entry"][0]
        self.assertEqual(list(iter_webhook_referrals(payload)), events)

    @patch(f"{_MOD}.request_meta_json", return_value=_graph_payload())
    def test_resolution_populates_message_and_reuses_persistent_cache(
        self, mock_request
    ):
        account = self._account()
        first = self._message(account, referral=_referral())
        second = self._message(account, referral=_referral())

        resolve_message_attribution(first)
        resolve_message_attribution(second)

        self.assertEqual(first.attribution_status, "Resolved")
        self.assertEqual(first.meta_campaign_id, "campaign-123")
        self.assertEqual(first.meta_adset_id, "adset-123")
        self.assertEqual(second.meta_campaign_id, "campaign-123")
        mock_request.assert_called_once()
        self.assertNotIn("secret-ads-token", first.attribution_error or "")

    @patch(f"{_MOD}.request_meta_json", side_effect=frappe.ValidationError("denied"))
    def test_resolution_failure_is_nonfatal(self, _mock_request):
        account = self._account()
        message = self._message(account, referral=_referral())

        resolve_message_attribution(message)

        self.assertEqual(message.attribution_status, "Failed")
        self.assertIn("denied", message.attribution_error)
        referral = serialize_referral(message)
        self.assertEqual(referral["source_id"], "120249647384630076")
        self.assertIsNone(referral["campaign"])
        self.assertEqual(referral["resolution_status"], "failed")

    @patch(f"{_MOD}.request_meta_json", return_value=_graph_payload())
    def test_serialized_referral_has_full_nested_contract(self, _mock_request):
        account = self._account()
        message = self._message(account, referral=_referral())
        resolve_message_attribution(message)

        payload = serialize_referral(message)

        self.assertEqual(payload["ctwa_clid"], "click-id")
        self.assertEqual(payload["ad"]["id"], "120249647384630076")
        self.assertEqual(payload["adset"]["id"], "adset-123")
        self.assertEqual(payload["campaign"]["id"], "campaign-123")
        self.assertEqual(payload["resolution_status"], "resolved")

    @patch(f"{_MOD}.request_meta_json", return_value=_graph_payload())
    @patch("frappe_whatsapp.utils.routing.make_post_request")
    def test_first_client_delivery_is_enriched_and_sent_once(
        self, mock_post, _mock_request
    ):
        account = self._account()
        app = self._client_app()
        message = self._message(account, referral=_referral())
        frappe.db.set_value(
            "WhatsApp Message",
            message.name,
            "routed_app",
            app.name,
            update_modified=False,
        )

        forward_incoming_to_app_by_name(
            incoming_message_name=str(message.name))
        forward_incoming_to_app_by_name(
            incoming_message_name=str(message.name))

        mock_post.assert_called_once()
        forwarded = json.loads(mock_post.call_args.kwargs["data"])
        referral = forwarded["message"]["referral"]
        self.assertEqual(referral["campaign"]["id"], "campaign-123")
        self.assertEqual(referral["resolution_status"], "resolved")

    @patch(f"{_MOD}.request_meta_json", return_value=_graph_payload())
    def test_backfill_preview_apply_and_repeat_are_idempotent(self, mock_request):
        account = self._account()
        message_id = f"wamid.{frappe.generate_hash(length=12)}"
        message = self._message(account, message_id=message_id)
        raw_payload = {
            "entry": [{
                "changes": [{
                    "value": {"messages": [{
                        "id": message_id,
                        "referral": _referral(),
                    }]}
                }]
            }]
        }

        with patch(
            f"{_MOD}._get_referral_log_rows",
            return_value=[{"meta_data": json.dumps(raw_payload)}],
        ):
            preview = backfill_campaign_attribution(dry_run=True)
            message.reload()
            self.assertEqual(preview["matched"], 1)
            self.assertEqual(preview["unique_ads"], 1)
            self.assertFalse(message.referral_source_id)

            applied = backfill_campaign_attribution(dry_run=False)
            message.reload()
            self.assertEqual(applied["updated"], 1)
            self.assertEqual(message.meta_campaign_id, "campaign-123")

            repeated = backfill_campaign_attribution(dry_run=False)
            self.assertEqual(repeated["updated"], 0)

        mock_request.assert_called_once()
