from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spring_toolkit_mcp.runtime import ActuatorClient, AppTarget, load_applications, redact_actuator_payload


class RuntimeTests(unittest.TestCase):
    def test_loads_named_actuator_applications(self) -> None:
        apps = load_applications(
            {
                "SPRING_TOOLKIT_ACTUATOR_BASE_URLS": (
                    "orders=http://localhost:8080/actuator;billing=http://localhost:8081/actuator"
                ),
                "SPRING_TOOLKIT_ACTUATOR_USERNAME": "admin",
                "SPRING_TOOLKIT_ACTUATOR_PASSWORD": "secret",
            }
        )

        self.assertEqual([app.name for app in apps], ["orders", "billing"])
        self.assertEqual(apps[0].base_url, "http://localhost:8080/actuator")
        self.assertEqual(apps[0].username, "admin")

    def test_redacts_actuator_env_payload(self) -> None:
        payload = {
            "propertySources": [
                {
                    "name": "applicationConfig",
                    "properties": {
                        "spring.datasource.password": {"value": "secret"},
                        "server.port": {"value": "8080"},
                    },
                }
            ]
        }

        redacted = redact_actuator_payload(payload)

        properties = redacted["propertySources"][0]["properties"]
        self.assertEqual(properties["spring.datasource.password"], "<redacted>")
        self.assertEqual(properties["server.port"]["value"], "8080")

    def test_logger_mutation_requires_policy_flag(self) -> None:
        client = ActuatorClient(
            applications=[AppTarget(name="orders", base_url="http://localhost:8080/actuator")],
            enable_logger_mutation=False,
        )

        with self.assertRaises(PermissionError):
            client.change_logger_level("orders", "com.acme.orders", "DEBUG")


if __name__ == "__main__":
    unittest.main()

