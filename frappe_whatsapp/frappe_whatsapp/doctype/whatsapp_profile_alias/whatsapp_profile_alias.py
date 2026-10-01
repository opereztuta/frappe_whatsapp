from frappe.model.document import Document


class WhatsAppProfileAlias(Document):
    def before_validate(self) -> None:
        from frappe_whatsapp.utils.identity import (
            alias_key,
            normalize_alias,
        )

        self.identity_scope = str(self.identity_scope or "").strip()
        self.alias_value = normalize_alias(
            str(self.alias_type or ""), self.alias_value
        )
        if self.identity_scope and self.alias_type and self.alias_value:
            self.alias_key = alias_key(
                self.identity_scope,
                self.alias_type,
                self.alias_value,
            )
