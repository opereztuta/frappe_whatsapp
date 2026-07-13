# Copyright (c) 2025, Shridhar Patil and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_account.whatsapp_account import (
	validate_account_connection,
)


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class _Account(SimpleNamespace):
	def get(self, field, default=None):
		return getattr(self, field, default)

	def get_password(self, field):
		return getattr(self, field, None)


def _account(**kwargs):
	defaults = {
		"name": "test-account",
		"url": "https://graph.facebook.com",
		"version": "v24.0",
		"business_id": "waba-id",
		"phone_id": "phone-id",
		"token": "token",
		"app_id": "app-id",
		"app_secret": "app-secret",
	}
	defaults.update(kwargs)
	return _Account(**defaults)


_MOD = (
	"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_account.whatsapp_account"
)


class UnitTestWhatsAppAccount(FrappeTestCase):
	"""
	Unit tests for WhatsAppAccount.
	Use this class for testing individual functions and methods.
	"""

	@patch(f"{_MOD}.get_paginated_data")
	@patch(f"{_MOD}.request_meta_json")
	def test_valid_permanent_system_user_connection(self, mock_request, mock_pages):
		mock_request.side_effect = [
			{"id": "system-user"},
			{
				"data": {
					"is_valid": True,
					"type": "SYSTEM_USER",
					"expires_at": 0,
					"scopes": [
						"whatsapp_business_management",
						"whatsapp_business_messaging",
					],
				}
			},
		]
		mock_pages.return_value = [{"id": "phone-id"}]

		result = validate_account_connection(_account())

		self.assertTrue(result["valid"])
		self.assertTrue(result["production_ready"])
		self.assertEqual(result["token_type"], "SYSTEM_USER")
		self.assertEqual(result["warnings"], [])

	@patch(f"{_MOD}.get_paginated_data", return_value=[{"id": "other-phone"}])
	@patch(f"{_MOD}.request_meta_json", return_value={"id": "system-user"})
	def test_phone_must_belong_to_configured_waba(self, _mock_request, _mock_pages):
		with self.assertRaises(frappe.ValidationError) as raised:
			validate_account_connection(_account())

		self.assertIn("does not belong to WABA", str(raised.exception))

	@patch(f"{_MOD}.get_paginated_data", return_value=[{"id": "phone-id"}])
	@patch(f"{_MOD}.request_meta_json")
	def test_missing_required_scopes_is_rejected(self, mock_request, _mock_pages):
		mock_request.side_effect = [
			{"id": "user"},
			{
				"data": {
					"is_valid": True,
					"type": "SYSTEM_USER",
					"scopes": ["whatsapp_business_management"],
				}
			},
		]

		with self.assertRaises(frappe.ValidationError) as raised:
			validate_account_connection(_account())

		self.assertIn("whatsapp_business_messaging", str(raised.exception))

	@patch(f"{_MOD}.get_paginated_data", return_value=[{"id": "phone-id"}])
	@patch(f"{_MOD}.request_meta_json", return_value={"id": "user"})
	def test_missing_app_secret_keeps_basic_validation_available(
		self, mock_request, _mock_pages
	):
		result = validate_account_connection(_account(app_secret=""))

		self.assertTrue(result["valid"])
		self.assertFalse(result["production_ready"])
		self.assertEqual(result["token_type"], "UNKNOWN")
		self.assertIsNone(result["required_scopes_present"])
		self.assertEqual(mock_request.call_count, 1)

	@patch(f"{_MOD}.get_paginated_data", return_value=[{"id": "phone-id"}])
	@patch(f"{_MOD}.request_meta_json")
	def test_user_token_is_reported_as_not_production_ready(
		self, mock_request, _mock_pages
	):
		mock_request.side_effect = [
			{"id": "user"},
			{
				"data": {
					"is_valid": True,
					"type": "USER",
					"expires_at": 1783735200,
					"scopes": list({
						"whatsapp_business_management",
						"whatsapp_business_messaging",
					}),
				}
			},
		]

		result = validate_account_connection(_account())

		self.assertFalse(result["production_ready"])
		self.assertEqual(result["token_type"], "USER")
		self.assertTrue(result["expires_at"])
		self.assertTrue(result["warnings"])


class IntegrationTestWhatsAppAccount(FrappeTestCase):
	"""
	Integration tests for WhatsAppAccount.
	Use this class for testing interactions between multiple components.
	"""

	pass
