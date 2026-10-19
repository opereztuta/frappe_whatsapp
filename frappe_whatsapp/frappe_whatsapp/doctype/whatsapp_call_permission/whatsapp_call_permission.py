from __future__ import annotations

import hashlib

from frappe.model.document import Document
import frappe

from frappe_whatsapp.utils.identity import normalize_phone


class WhatsAppCallPermission(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        contact_profile: DF.Link | None
        expires_at: DF.Datetime | None
        is_permanent: DF.Check
        last_checked_at: DF.Datetime | None
        last_request_message: DF.Link | None
        last_requested_at: DF.Datetime | None
        permission_status: DF.Literal["No Permission", "Temporary", "Permanent", "Rejected", "Expired", "Unknown"]
        phone_number: DF.Data | None
        raw_meta_state: DF.JSON | None
        recipient: DF.Data | None
        response_source: DF.Data | None
        whatsapp_account: DF.Link
    # end: auto-generated types

    def autoname(self):
        self.phone_number = normalize_phone(self.phone_number) or None
        if self.phone_number:
            self.name = f"{self.phone_number}-{self.whatsapp_account}"
        elif self.recipient:
            key = f"{self.whatsapp_account}\0{self.recipient}"
            self.name = (
                "recipient-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
            )
        else:
            frappe.throw(
                "A phone number or recipient is required for a call permission."
            )
