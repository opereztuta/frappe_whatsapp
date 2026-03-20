from __future__ import annotations

from frappe.model.document import Document


class WhatsAppStatusWebhookLog(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        attempts: DF.Int
        claim_expires_at: DF.Datetime | None
        current_status: DF.Data | None
        delivery_status: DF.Literal["Pending", "Processing", "Delivered", "Failed", "Skipped"]
        error: DF.SmallText | None
        event_id: DF.Data | None
        last_attempted_at: DF.Datetime | None
        message_name: DF.Link | None
        next_retry_at: DF.Datetime | None
        payload: DF.JSON | None
        previous_status: DF.Data | None
        response_body: DF.SmallText | None
        response_code: DF.Data | None
        source_app: DF.Link | None
    # end: auto-generated types
