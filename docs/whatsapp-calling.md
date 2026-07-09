# WhatsApp Outbound Calling

This app can request WhatsApp call permission, track the permission reply, and
ask Asterisk/FreePBX to originate the call through AMI.

## FreePBX/Asterisk setup

- Enable WhatsApp Business Calling for the Meta app and WhatsApp phone number.
- Configure WhatsApp SIP calling in FreePBX/Asterisk following Meta's SIP guide.
- Create or verify an outbound route that can dial WhatsApp users from an
  internal extension.
- Create a restricted AMI user with Originate permission.
- Manually test the FreePBX route from an agent extension before enabling the
  Frappe Call button.

## Frappe setup

- Open **WhatsApp Calling Settings**.
- Enable calling.
- Select an approved WhatsApp template marked **Is Call Permission Request**.
- Enter AMI host, port, username, password, and TLS setting.
- Configure:
  - **Agent Channel Template**: defaults to `Local/{extension}@from-internal`
  - **Destination Context**: defaults to `from-internal`
  - **Destination Number Template**: defaults to `{number}`
- Create one **WhatsApp Call Agent** per chat user and set their PBX extension.

`{number}` is the WhatsApp number without a leading `+`; `{e164}` includes the
leading `+`; `{extension}` is the mapped PBX extension.
