// Copyright (c) 2022, Shridhar Patil and contributors
// For license information, please see license.txt

var WHATSAPP_MESSAGE_BLOCKING_API = "frappe_whatsapp.frappe_whatsapp.api.blocking";

frappe.ui.form.on('WhatsApp Message', {
	onload: function(frm) {
		frappe.db.get_value('WhatsApp Account', frm.doc.whatsapp_account, 'allow_auto_read_receipt').then(value => {
			if (value && frm.doc.type === "Incoming" && frm.doc.status !== "marked as read" && frm.doc.message_id) {
				send_read_receipt(frm);
			}
		});
	},
	refresh: function(frm) {
		if (frm.doc.type == 'Incoming'){
			frm.add_custom_button(__("Reply"), function(){
				frappe.new_doc("WhatsApp Message", {"to": frm.doc.from});

			});
			add_block_sender(frm);
		}

		// add custom button to send read receipt
		add_mark_as_read(frm);
	}
});

function add_block_sender(frm) {
	if (!frm.doc.name || frm.doc.type !== "Incoming" || !frm.doc.from) {
		return;
	}

	frm.add_custom_button(__("Block Sender"), function() {
		frappe.prompt(
			[
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason"),
					reqd: 1,
				},
			],
			function(values) {
				frappe.call({
					method: `${WHATSAPP_MESSAGE_BLOCKING_API}.block_contact`,
					args: {
						message_name: frm.doc.name,
						reason: values.reason,
						sync_meta: 1,
					},
					freeze: true,
					freeze_message: __("Blocking sender..."),
					callback: function(r) {
						const meta = (r.message && r.message.meta) || {};
						const sync_failed = meta.ok === false && !meta.skipped;
						frappe.show_alert({
							message: sync_failed
								? __("Sender blocked locally. Meta sync failed.")
								: __("Sender blocked."),
							indicator: sync_failed ? "orange" : "green",
						});
					},
				});
			},
			__("Block Sender"),
			__("Block")
		);
	});
}

// custom button
function add_mark_as_read(frm){
	if(frm.doc.type === "Outgoing" || frm.doc.status == "marked as read" || !frm.doc.message_id)
		return
	
	frappe.db.get_value('WhatsApp Account', frm.doc.whatsapp_account, 'allow_auto_read_receipt').then(value => {
		if (value) return; // return if auto read receipt is enabled

		frm.add_custom_button(__('Mark as read'), function(){
			send_read_receipt(frm);
		});
	});
}

function send_read_receipt(frm) {
	frappe.call({
		doc: frm.doc,
		method: "send_read_receipt",
		callback: function(r) {
			if (r && r.message) {
				frappe.msgprint(__('Marked as read'));
			}
		}
	});
}
