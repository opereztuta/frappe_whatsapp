// Copyright (c) 2025, Shridhar Patil and contributors
// For license information, please see license.txt

frappe.ui.form.on("WhatsApp Account", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Validate Meta Connection"), () => {
			frappe.call({
				method: "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_account.whatsapp_account.validate_meta_connection",
				args: { whatsapp_account: frm.doc.name },
				freeze: true,
				freeze_message: __("Validating Meta connection..."),
				callback(r) {
					if (!r.message) {
						return;
					}

					const result = r.message;
					const warnings = (result.warnings || [])
						.map((warning) => frappe.utils.escape_html(warning))
						.join("<br>");
					const details = [
						__("Token type: {0}", [frappe.utils.escape_html(result.token_type || "UNKNOWN")]),
						__("Phone belongs to WABA: {0}", [result.phone_matches_waba ? __("Yes") : __("No")]),
						__("Required scopes present: {0}", [
							result.required_scopes_present === null
								? __("Not verified")
								: result.required_scopes_present ? __("Yes") : __("No")
						]),
					];
					if (result.expires_at) {
						details.push(__("Expires at: {0}", [frappe.utils.escape_html(result.expires_at)]));
					}
					if (warnings) {
						details.push(`<br>${warnings}`);
					}

					frappe.msgprint({
						title: result.production_ready
							? __("Meta Connection Ready")
							: __("Meta Connection Valid with Warnings"),
						message: details.join("<br>"),
						indicator: result.production_ready ? "green" : "orange",
					});
				},
			});
		});
	},
});
