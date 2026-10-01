from __future__ import annotations

import hashlib

from frappe.model.document import Document


class WhatsAppProfileAccountState(Document):
    def autoname(self) -> None:
        raw = f"{self.whatsapp_profile}\0{self.whatsapp_account}"
        self.state_key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.name = self.state_key

