import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from requests import Response

from frappe_whatsapp.utils.meta import get_paginated_data, request_meta_json


def _response(status: int, payload: dict) -> Response:
    response = Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    response.headers["content-type"] = "application/json"
    return response


class TestMetaRequests(FrappeTestCase):
    @patch("frappe_whatsapp.utils.meta.requests.request")
    def test_oauth_error_includes_account_code_and_subcode(self, mock_request):
        mock_request.return_value = _response(
            401,
            {
                "error": {
                    "message": "Error validating access token: Session has expired.",
                    "type": "OAuthException",
                    "code": 190,
                    "error_subcode": 463,
                }
            },
        )

        with self.assertRaises(frappe.ValidationError) as raised:
            request_meta_json(
                "GET",
                "https://graph.facebook.com/v24.0/me",
                account_name="expired-account",
                operation="access-token validation",
                headers={"Authorization": "Bearer secret"},
            )

        message = str(raised.exception)
        self.assertIn("expired-account", message)
        self.assertIn("code 190", message)
        self.assertIn("subcode 463", message)
        self.assertNotIn("secret", message)

    @patch("frappe_whatsapp.utils.meta.requests.request")
    def test_paginated_collection_follows_all_pages(self, mock_request):
        mock_request.side_effect = [
            _response(
                200,
                {
                    "data": [{"id": "one"}],
                    "paging": {
                        "next": "https://graph.facebook.com/v24.0/waba/items?after=one"
                    },
                },
            ),
            _response(200, {"data": [{"id": "two"}]}),
        ]

        data = get_paginated_data(
            "https://graph.facebook.com/v24.0/waba/items",
            account_name="account",
            operation="item sync",
            headers={"Authorization": "Bearer secret"},
            params={"limit": 1},
        )

        self.assertEqual([item["id"] for item in data], ["one", "two"])
        self.assertEqual(mock_request.call_count, 2)
        self.assertIsNone(mock_request.call_args_list[1].kwargs["params"])
