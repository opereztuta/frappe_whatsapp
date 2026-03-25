# Copyright (c) 2022, Shridhar Patil and Contributors
# See license.txt

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import (  # noqa: E501
    _normalize_meta_language_code,
    _resolve_language_link,
)


class TestWhatsAppTemplates(FrappeTestCase):
    def test_normalize_meta_language_code_uses_underscores(self):
        self.assertEqual(_normalize_meta_language_code("en-US"), "en_US")
        self.assertEqual(_normalize_meta_language_code("es"), "es")

    def test_resolve_language_link_accepts_meta_separator_variants(self):
        with patch(
            "frappe_whatsapp.frappe_whatsapp.doctype."
            "whatsapp_templates.whatsapp_templates.frappe.db.exists"
        ) as mock_exists:
            mock_exists.side_effect = lambda doctype, name: name in {
                "en-US", "es"}

            self.assertEqual(_resolve_language_link("en_US"), "en-US")
            self.assertEqual(_resolve_language_link("es"), "es")
            self.assertEqual(_resolve_language_link("pt_BR"), "")
