"""Tests for server-defined menu and authorization of its read-only actions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import interaction_lab as lab


class InteractionMenuTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "menu.json"
        self.config = {
            "title": "Example", "description": "Synthetic", "actions": [
                {"id": "first", "label": "First", "enabled": True,
                 "result": {"heading": "Details", "details": ["A"]}},
                {"id": "off", "label": "Off", "enabled": False,
                 "result": {"heading": "Hidden", "details": []}},
            ]}
        self.write()
        self.patch = patch.object(lab, "MENU_PATH", self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self):
        self.path.write_text(json.dumps(self.config), encoding="utf-8")

    def test_menu_excludes_results_until_action_is_requested(self):
        menu = lab.public_menu()
        self.assertEqual(menu["actions"][0], {"id": "first", "label": "First", "enabled": True})
        self.assertEqual(lab.run_action("first")["details"], ["A"])

    def test_reloads_configuration_without_html_rebuild(self):
        self.config["actions"][0]["label"] = "Changed"
        self.config["actions"][0]["result"]["details"] = ["Fresh"]
        self.write()
        self.assertEqual(lab.public_menu()["actions"][0]["label"], "Changed")
        self.assertEqual(lab.run_action("first")["details"], ["Fresh"])

    def test_disabled_and_unknown_actions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "disabled"):
            lab.run_action("off")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            lab.run_action("missing")
        self.config["actions"][0]["enabled"] = False
        self.write()
        with self.assertRaisesRegex(ValueError, "disabled"):
            lab.run_action("first")

    def test_app_only_visibility_is_registered(self):
        from mcp.server.apps import Apps
        apps = Apps()
        lab.register(apps)
        tools = {binding.kwargs["name"]: binding for binding, _ in apps._tools}
        for name in ("datum_menu_refresh", "datum_menu_action"):
            self.assertEqual(tools[name].meta["ui"]["visibility"], ["app"])
            self.assertEqual(tools[name].meta["ui"]["resourceUri"], lab.APP_URI)
        self.assertNotIn("visibility", tools["datum_open_interaction_lab"].meta["ui"])
    def test_invalid_menu_cannot_be_executed(self):
        self.config["actions"].append(self.config["actions"][0])
        self.write()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            lab.public_menu()


if __name__ == "__main__":
    unittest.main()


