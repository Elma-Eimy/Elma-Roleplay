"""在隔离源码副本中核对 API 导航与真实请求模型，不调用业务接口。"""

from collections import Counter
from pathlib import Path
import unittest

from fastapi.routing import APIRoute

from application.factory import create_app
from scripts.api_documentation import (
    DOMAIN_DOCUMENTS, documented_routes, request_examples, unknown_model_fields,
)


class ApiDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = Path(__file__).resolve().parents[2] / "project_docs"
        cls.routes = {
            (method, route.path): route
            for route in create_app().routes if isinstance(route, APIRoute)
            for method in route.methods
        }

    def test_summary_covers_each_business_route_once(self):
        rows = documented_routes((self.docs / "API_TABLE.md").read_text(encoding="utf-8"))
        self.assertEqual([], [route for route, count in Counter(rows).items() if count != 1])
        self.assertEqual(set(self.routes), set(rows))

    def test_all_json_body_routes_have_valid_documented_examples(self):
        expected = {
            key for key, route in self.routes.items()
            if route.body_field is not None
            and route.body_field.field_info.media_type == "application/json"
        }
        covered = set()
        for name in DOMAIN_DOCUMENTS:
            text = (self.docs / "docs" / "api" / name).read_text(encoding="utf-8")
            examples = list(request_examples(text))
            self.assertEqual(text.count("<!-- request-example:"), len(examples), name)
            for line, keys, payload in examples:
                for key in keys:
                    with self.subTest(document=name, line=line, route=key):
                        self.assertIn(key, expected, "样本必须绑定真实 JSON 请求接口")
                        field = self.routes[key].body_field
                        self.assertEqual([], unknown_model_fields(payload, field.field_info.annotation))
                        _, errors = field.validate(payload, {}, loc=("body",))
                        self.assertFalse(errors, errors)
                        covered.add(key)
        self.assertEqual(expected, covered, "新增 JSON 请求接口需在领域文档中补充示例")

    def test_example_checks_catch_required_fields_types_and_unknown_names(self):
        chat = self.routes[("POST", "/chat")].body_field
        for payload in ({"user_message": "hello"}, {"session_id": "bad", "user_message": "hello"}):
            with self.subTest(payload=payload):
                _, errors = chat.validate(payload, {}, loc=("body",))
                self.assertTrue(errors)
        self.assertEqual(
            ["body.user_mesage"],
            unknown_model_fields({"session_id": 1, "user_message": "hello", "user_mesage": "typo"}, chat.field_info.annotation),
        )
        translation = self.routes[("POST", "/characters/translate")].body_field
        self.assertEqual(
            ["body.card.descripton"],
            unknown_model_fields({"card": {"name": "test", "descripton": "typo"}}, translation.field_info.annotation),
        )
        settings = self.routes[("PUT", "/utils/settings")].body_field
        self.assertEqual(
            ["body.model_profiles[0].lable"],
            unknown_model_fields({"model_profiles": [{"id": "test", "lable": "typo"}]}, settings.field_info.annotation),
        )


if __name__ == "__main__":
    unittest.main()
