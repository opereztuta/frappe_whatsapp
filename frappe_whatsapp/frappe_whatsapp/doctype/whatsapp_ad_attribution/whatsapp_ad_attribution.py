from frappe.model.document import Document


class WhatsAppAdAttribution(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        ad_account_id: DF.Data | None
        ad_id: DF.Data
        ad_name: DF.Data | None
        adset_id: DF.Data | None
        adset_name: DF.Data | None
        cache_key: DF.Data
        campaign_id: DF.Data | None
        campaign_name: DF.Data | None
        effective_status: DF.Data | None
        resolved_at: DF.Datetime | None
        whatsapp_account: DF.Link
    # end: auto-generated types
    pass
