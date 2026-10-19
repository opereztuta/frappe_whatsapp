from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime, now_datetime

from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_call_permission.whatsapp_call_permission import (
    WhatsAppCallPermission,
)
from frappe_whatsapp.utils.calling import (
    _upsert_permission,
    get_local_permission,
    request_call_permission,
)
from frappe_whatsapp.utils.identity import resolve_identity


class TestWhatsAppCallPermission(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.account = self._account()
        self.number = "15550101991"

    def tearDown(self):
        frappe.db.rollback()

    def _account(self):
        suffix = frappe.generate_hash(length=8)
        return frappe.get_doc(
            {
                "doctype": "WhatsApp Account",
                "account_name": f"Permission Regression {suffix}",
                "status": "Active",
                "token": "test-token",
                "url": "https://graph.facebook.com",
                "version": "v24.0",
                "phone_id": f"permission-{suffix}",
            }
        ).insert(ignore_permissions=True)

    def _upsert(self, **kwargs):
        values = dict(
            whatsapp_account=self.account.name,
            phone_number=self.number,
            state={"permission_status": "No Permission"},
        )
        values.update(kwargs)
        return _upsert_permission(**values)

    def _profile(self, number=None):
        return resolve_identity(
            whatsapp_account=self.account.name,
            identity={"phone": number or self.number},
        )

    def test_legacy_phone_row_is_reused_and_history_preserved(self):
        requested_at = now_datetime()
        first = self._upsert(last_requested_at=requested_at)
        profile = self._profile()
        updated = self._upsert(
            phone_number="+1 (555) 010-1991", contact_profile=profile.name
        )
        self.assertEqual(first.name, updated.name)
        self.assertEqual(updated.contact_profile, profile.name)
        self.assertEqual(get_datetime(updated.last_requested_at), requested_at)
        self.assertEqual(
            get_local_permission(
                "", self.account.name, contact_profile=profile.name
            ).name,
            first.name,
        )
        self.assertEqual(
            frappe.db.count(
                "WhatsApp Call Permission", {"whatsapp_account": self.account.name}
            ),
            1,
        )

    def test_deterministic_name_finds_legacy_row_with_missing_phone(self):
        first = self._upsert()
        frappe.db.set_value(
            "WhatsApp Call Permission", first.name, "phone_number", None
        )
        updated = self._upsert(contact_profile=self._profile().name)
        self.assertEqual(first.name, updated.name)
        self.assertEqual(updated.phone_number, self.number)

    def test_legacy_recipient_name_and_account_isolation(self):
        recipient = "test-business-user"
        first = self._upsert(phone_number="", recipient=recipient)
        self.assertTrue(first.name.startswith("recipient-"))
        legacy_name = "legacy-" + frappe.generate_hash(length=12)
        frappe.db.set_value("WhatsApp Call Permission", first.name, "name", legacy_name)
        self.assertEqual(
            self._upsert(phone_number="", recipient=recipient).name, legacy_name
        )
        other = self._account()
        second = self._upsert(
            whatsapp_account=other.name, phone_number="", recipient=recipient
        )
        self.assertNotEqual(second.name, legacy_name)
        self.assertEqual(
            get_local_permission("", self.account.name, recipient=recipient).name,
            legacy_name,
        )
        self.assertIsNone(get_local_permission(self.number, other.name))

    def test_conflicting_profile_is_not_relinked(self):
        original = self._profile()
        first = self._upsert(contact_profile=original.name)
        different = self._profile("15550101992")
        with self.assertRaises(frappe.ValidationError):
            self._upsert(contact_profile=different.name)
        self.assertEqual(
            frappe.db.get_value(
                "WhatsApp Call Permission", first.name, "contact_profile"
            ),
            original.name,
        )

    def test_multiple_identity_matches_are_rejected(self):
        profile = self._profile()
        self._upsert(contact_profile=profile.name)
        self._upsert(phone_number="15550101992")
        with self.assertRaises(frappe.ValidationError):
            get_local_permission(
                "15550101992", self.account.name, contact_profile=profile.name
            )

    def test_duplicate_legacy_rows_for_one_identifier_are_rejected(self):
        first = self._upsert()
        frappe.db.set_value(
            "WhatsApp Call Permission",
            first.name,
            "name",
            "legacy-" + frappe.generate_hash(length=12),
        )
        frappe.get_doc(
            {
                "doctype": "WhatsApp Call Permission",
                "whatsapp_account": self.account.name,
                "phone_number": self.number,
            }
        ).insert(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            self._upsert()

    def test_unrelated_insert_error_propagates(self):
        with patch.object(
            WhatsAppCallPermission,
            "insert",
            side_effect=RuntimeError("storage failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "storage failure"):
                self._upsert()

    def test_duplicate_custom_name_does_not_retry_as_hash(self):
        first = self._upsert()
        duplicate = frappe.get_doc(
            {
                "doctype": "WhatsApp Call Permission",
                "whatsapp_account": self.account.name,
                "phone_number": self.number,
            }
        )
        with self.assertRaises(frappe.DuplicateEntryError):
            duplicate.insert(ignore_permissions=True)
        self.assertEqual(duplicate.name, first.name)
        self.assertFalse(duplicate.flags.retry_count)

    def test_competing_insert_recovers_using_current_read(self):
        # Only isolated fixtures are committed for visibility to connection two.
        frappe.db.commit()
        original_insert = WhatsAppCallPermission.insert
        requested_at = now_datetime()
        try:
            for phone, recipient in [(self.number, ""), ("", "race-business-user")]:
                winner_names = []
                messages = list(frappe.local.message_log)

                def competing_insert(doc, *args, **kwargs):
                    # The loser has already established a repeatable-read snapshot.
                    with patch.object(
                        WhatsAppCallPermission, "insert", original_insert
                    ):
                        with self.primary_connection(), self.secondary_connection():
                            winner = self._upsert(
                                phone_number=phone,
                                recipient=recipient,
                                last_requested_at=requested_at,
                            )
                            winner_names.append(winner.name)
                            frappe.db.commit()
                        return original_insert(doc, *args, **kwargs)

                try:
                    with patch.object(
                        WhatsAppCallPermission,
                        "insert",
                        autospec=True,
                        side_effect=competing_insert,
                    ):
                        result = self._upsert(phone_number=phone, recipient=recipient)
                    self.assertEqual(result.name, winner_names[0])
                    self.assertEqual(frappe.local.message_log, messages)
                    self.assertEqual(
                        get_datetime(result.last_requested_at), requested_at
                    )
                    self.assertEqual(
                        frappe.db.count(
                            "WhatsApp Call Permission",
                            {"whatsapp_account": self.account.name},
                        ),
                        1,
                    )
                finally:
                    frappe.db.rollback()
                    for name in winner_names:
                        frappe.db.delete("WhatsApp Call Permission", {"name": name})
                    frappe.db.commit()
        finally:
            frappe.delete_doc("WhatsApp Account", self.account.name, force=True)
            frappe.db.commit()

    def test_real_message_hooks_reuse_permission_and_replay_sends_once(self):
        # Bypass unrelated template provisioning hooks for this local fixture.
        template = frappe.get_doc(
            {
                "doctype": "WhatsApp Templates",
                "name": "permission-template-" + frappe.generate_hash(length=8),
                "template_name": "permission_regression",
                "actual_name": "permission_regression",
                "template": "May we call you?",
                "language": "en",
                "language_code": "en_US",
                "category": "UTILITY",
                "is_call_permission_request": 1,
                "whatsapp_account": self.account.name,
            }
        )
        template.db_insert()
        response = Mock(content=b"{}")
        response.json.return_value = {
            "permission": {"status": "no_permission"},
            "actions": [
                {
                    "action_name": "send_call_permission_request",
                    "can_perform_action": True,
                }
            ],
        }
        calling = "frappe_whatsapp.utils.calling."
        message = (
            "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message."
        )
        with (
            patch(calling + "_ensure_enabled", return_value=SimpleNamespace(enabled=1)),
            patch(
                calling + "_resolve_call_permission_template",
                return_value=(template, "en", False),
            ),
            patch(calling + "filelock", side_effect=lambda *a, **kw: nullcontext()),
            patch(calling + "requests.get", return_value=response) as meta_get,
            patch(calling + "publish_call_update"),
            patch(message + "WhatsAppMessage._check_consent"),
            patch(message + "enforce_template_send_rules"),
            patch(
                message + "request_meta_json",
                return_value={
                    "messages": [{"id": "wamid.permission-regression"}],
                },
            ) as meta_send,
        ):
            params = dict(
                phone_number=self.number,
                whatsapp_account=self.account.name,
                agent_extension="772",
                idempotency_key="permission-regression-1234",
            )
            result = request_call_permission(**params)
            replay = request_call_permission(**params)
        self.assertTrue(result["ok"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(meta_get.call_count, 2)
        meta_send.assert_called_once()
        permission = get_local_permission(self.number, self.account.name)
        self.assertTrue(permission.contact_profile)
        sent = frappe.get_doc("WhatsApp Message", permission.last_request_message)
        self.assertEqual(sent.contact_profile, permission.contact_profile)
        self.assertEqual(sent.message_id, "wamid.permission-regression")
        refreshed = self._upsert()
        self.assertEqual(refreshed.last_request_message, sent.name)
        self.assertEqual(refreshed.last_requested_at, permission.last_requested_at)
        self.assertEqual(
            frappe.db.count(
                "WhatsApp Call Permission", {"whatsapp_account": self.account.name}
            ),
            1,
        )
