# Copyright (c) 2026, Shridhar Patil and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_calling_settings.whatsapp_calling_settings import (
    WhatsAppCallingSettings,
)


class TestWhatsAppCallingSettings(FrappeTestCase):
    def _settings(self, destination):
        return WhatsAppCallingSettings(
            {
                "doctype": "WhatsApp Calling Settings",
                "identity_destination_extension": destination,
            }
        )

    def test_bsuid_route_can_remain_disabled(self):
        settings = self._settings(None)
        settings.validate()
        self.assertFalse(settings.identity_destination_extension)

    def test_named_bsuid_destination_is_accepted(self):
        settings = self._settings("whatsapp-bsuid")
        settings.validate()
        self.assertEqual(settings.identity_destination_extension, "whatsapp-bsuid")

    def test_unsafe_destination_is_rejected(self):
        for destination in (
            "whatsapp-bsuid,1",
            "whatsapp-bsuid@from-internal",
            "x" * 65,
            "x\r\nAction: Originate",
        ):
            with self.subTest(destination=destination), self.assertRaises(
                frappe.ValidationError
            ):
                self._settings(destination).validate()
