import unittest
from types import SimpleNamespace

from task_local_agent import loopback_url, model_visible_tools


class LocalAgentHarnessTests(unittest.TestCase):
    def test_rejects_non_loopback_and_non_http_endpoints(self):
        self.assertEqual(loopback_url("http://127.0.0.1:11434/"), "http://127.0.0.1:11434")
        for endpoint in ("https://localhost:11434", "http://example.com", "http://127.0.0.1.example.com", "http://localhost@example.com"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                loopback_url(endpoint)

    def test_schemas_come_from_discovery_and_app_only_is_not_exposed(self):
        def tool(name, meta=None):
            return SimpleNamespace(name=name, description="sample", input_schema={"type": "object", "properties": {"machine_id": {"type": "string"}}}, meta=meta)
        allowed = tool("datum_get_machine")
        app_only = tool("datum_task_get", {"ui": {"visibility": ["app"]}})
        other = tool("unrelated_tool")
        rendered = model_visible_tools([allowed, app_only, other])
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0]["function"]["name"], "datum_get_machine")
        self.assertEqual(rendered[0]["function"]["parameters"], allowed.input_schema)


if __name__ == "__main__":
    unittest.main()
