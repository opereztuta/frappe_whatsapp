frappe.listview_settings['WhatsApp Templates'] = {

	onload: function(listview) {
		listview.page.add_inner_button(__("Sync from Meta"), function() {
			frappe.prompt([
				{
					fieldname: "whatsapp_account",
					fieldtype: "Link",
					label: __("WhatsApp Account"),
					options: "WhatsApp Account",
					reqd: 1,
					get_query: function() {
						return { filters: { status: "Active" } };
					}
				}
			], function(values) {
				frappe.call({
					method: "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.fetch",
					args: { whatsapp_account: values.whatsapp_account },
					freeze: true,
					freeze_message: __("Syncing templates from Meta..."),
					callback: function(r) {
						if (r.message) {
							frappe.msgprint({
								title: __("Sync Complete"),
								message: r.message,
								indicator: "green"
							});
							listview.refresh();
						}
					}
				});
			}, __("Sync Templates from Meta"), __("Sync"));
		});
	}
};
