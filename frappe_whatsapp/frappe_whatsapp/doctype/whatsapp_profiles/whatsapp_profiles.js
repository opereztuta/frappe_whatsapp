// Copyright (c) 2025, Shridhar Patil and contributors
// For license information, please see license.txt

var WHATSAPP_BLOCKING_API = "frappe_whatsapp.frappe_whatsapp.api.blocking";

frappe.ui.form.on("WhatsApp Profiles", {
	refresh(frm) {
		if (frm.is_new()) {
			render_blocking_status(frm, {
				requires_whatsapp_account: true,
				is_blocked: false,
				block_record: null
			});
			return;
		}

		refresh_blocking_state(frm);
	},
});

function refresh_blocking_state(frm) {
	frappe.call({
		method: `${WHATSAPP_BLOCKING_API}.get_profile_block_state`,
		args: {
			profile_name: frm.doc.name,
			whatsapp_account: frm.doc.whatsapp_account || null,
		},
		callback(r) {
			const state = r.message || {};
			frm._whatsapp_block_state = state;
			render_blocking_status(frm, state);
			add_blocking_buttons(frm, state);
		},
		error() {
			render_blocking_status(frm, {
				error: __("Unable to load blocking status."),
				is_blocked: false,
				block_record: null,
			});
		},
	});
}

function add_blocking_buttons(frm, state) {
	frm.remove_custom_button(__("Block Contact"));
	frm.remove_custom_button(__("Unblock Contact"));
	frm.remove_custom_button(__("View Block Record"));

	if (state && state.is_blocked) {
		frm.add_custom_button(__("Unblock Contact"), () => {
			prompt_profile_block_action(frm, "unblock");
		});
	} else {
		frm.add_custom_button(__("Block Contact"), () => {
			prompt_profile_block_action(frm, "block");
		});
	}

	if (state && state.block_record && state.block_record.name) {
		frm.add_custom_button(__("View Block Record"), () => {
			frappe.set_route(
				"Form",
				"WhatsApp Blocked Contact",
				state.block_record.name
			);
		});
	}
}

function prompt_profile_block_action(frm, action) {
	const is_block = action === "block";
	const fields = [];

	if (!frm.doc.whatsapp_account) {
		fields.push({
			fieldname: "whatsapp_account",
			fieldtype: "Link",
			label: __("WhatsApp Account"),
			options: "WhatsApp Account",
			reqd: 1,
		});
	}

	fields.push({
		fieldname: "reason",
		fieldtype: "Small Text",
		label: __("Reason"),
		reqd: is_block ? 1 : 0,
	});

	frappe.prompt(
		fields,
		(values) => {
			run_profile_block_action(frm, action, values || {});
		},
		is_block ? __("Block Contact") : __("Unblock Contact"),
		is_block ? __("Block") : __("Unblock")
	);
}

function run_profile_block_action(frm, action, values) {
	const is_block = action === "block";
	const method = is_block
		? `${WHATSAPP_BLOCKING_API}.block_profile_contact`
		: `${WHATSAPP_BLOCKING_API}.unblock_profile_contact`;

	frappe.call({
		method,
		args: {
			profile_name: frm.doc.name,
			whatsapp_account: values.whatsapp_account || frm.doc.whatsapp_account,
			reason: values.reason || "",
			sync_meta: 1,
		},
		freeze: true,
		freeze_message: is_block
			? __("Blocking contact...")
			: __("Unblocking contact..."),
		callback(r) {
			show_blocking_result(is_block, r.message || {});
			refresh_blocking_state(frm);
		},
	});
}

function show_blocking_result(is_block, result) {
	const meta = result.meta || {};
	let message = is_block
		? __("Contact blocked.")
		: __("Contact unblocked.");
	let indicator = "green";

	if (meta && meta.ok === false && !meta.skipped) {
		message = is_block
			? __("Contact blocked locally. Meta sync failed.")
			: __("Contact unblocked locally. Meta sync failed.");
		indicator = "orange";
	}

	frappe.show_alert({ message, indicator });
}

function render_blocking_status(frm, state) {
	const field = frm.get_field("blocking_status_html");
	if (!field || !field.$wrapper) {
		return;
	}

	if (state && state.error) {
		field.$wrapper.html(`<div class="text-muted">${escape_html(state.error)}</div>`);
		return;
	}

	const record = (state && state.block_record) || {};
	const is_blocked = Boolean(state && state.is_blocked);
	const status_label = is_blocked ? __("Blocked") : __("Not Blocked");
	const indicator = is_blocked ? "red" : "green";
	const account = (state && state.whatsapp_account) || frm.doc.whatsapp_account || "";
	const contact_number = (state && state.contact_number) || frm.doc.number || "";
	const meta_status = record.meta_status || "";
	const last_synced_at = record.last_synced_at || "";
	const last_error = record.last_error || "";
	const block_record = record.name || "";

	let body = `
		<div class="frappe-control">
			<div class="mb-2">
				<span class="indicator ${indicator}">${escape_html(status_label)}</span>
			</div>
			<div class="text-muted small">
				${__("Number")}: ${escape_html(contact_number || "-")}<br>
				${__("WhatsApp Account")}: ${escape_html(account || "-")}<br>
				${__("Meta Status")}: ${escape_html(meta_status || "-")}<br>
				${__("Last Synced At")}: ${escape_html(last_synced_at || "-")}
			</div>`;

	if (block_record) {
		body += `
			<div class="text-muted small">
				${__("Block Record")}: ${escape_html(block_record)}
			</div>`;
	}

	if (last_error) {
		body += `
			<div class="text-danger small mt-2">
				${escape_html(last_error)}
			</div>`;
	}

	if (state && state.requires_whatsapp_account) {
		body += `
			<div class="text-muted small mt-2">
				${__("Select a WhatsApp Account to manage blocking.")}
			</div>`;
	}

	body += "</div>";
	field.$wrapper.html(body);
}

function escape_html(value) {
	return $("<div>").text(value || "").html();
}
