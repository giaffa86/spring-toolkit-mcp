from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spring_toolkit_mcp.runtime import ActuatorClient, AppTarget, load_applications, redact_actuator_payload


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self.body
            self.body = b""
            return chunk
        chunk = self.body[:size]
        self.body = self.body[size:]
        return chunk


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

    def test_reads_json_actuator_endpoint_with_query_params(self) -> None:
        client = ActuatorClient(
            applications=[AppTarget(name="orders", base_url="http://localhost:8080/actuator")],
        )

        with patch("urllib.request.urlopen", return_value=FakeResponse(b'{"events": []}')) as urlopen:
            result = client.get_audit_events(
                "orders",
                principal="alice",
                after="2026-06-13T00:00:00Z",
                event_type="AUTHENTICATION_SUCCESS",
            )

        self.assertEqual(result, {"events": []})
        request = urlopen.call_args.args[0]
        parsed = urlparse(request.full_url)
        self.assertEqual(parsed.path, "/actuator/auditevents")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "principal": ["alice"],
                "after": ["2026-06-13T00:00:00Z"],
                "type": ["AUTHENTICATION_SUCCESS"],
            },
        )

    def test_configprops_redacts_sensitive_payload(self) -> None:
        client = ActuatorClient(
            applications=[AppTarget(name="orders", base_url="http://localhost:8080/actuator")],
        )

        with patch(
            "urllib.request.urlopen",
            return_value=FakeResponse(b'{"contexts": {"app": {"properties": {"password": "secret"}}}}'),
        ):
            result = client.get_config_properties("orders")

        self.assertEqual(result["contexts"]["app"]["properties"]["password"], "<redacted>")

    def test_prometheus_returns_bounded_text_payload(self) -> None:
        client = ActuatorClient(
            applications=[AppTarget(name="orders", base_url="http://localhost:8080/actuator")],
        )

        with patch(
            "urllib.request.urlopen",
            return_value=FakeResponse(b"metric_one 1\nmetric_two 2\n", headers={"Content-Type": "text/plain"}),
        ):
            result = client.get_prometheus("orders", max_chars=12)

        self.assertEqual(result["content"], "metric_one 1")
        self.assertTrue(result["truncated"])

    def test_sensitive_downloads_require_policy_flag(self) -> None:
        client = ActuatorClient(
            applications=[AppTarget(name="orders", base_url="http://localhost:8080/actuator")],
        )

        with self.assertRaises(PermissionError):
            client.get_log_file("orders")
        with self.assertRaises(PermissionError):
            client.get_heap_dump_metadata("orders")

    def test_session_delete_requires_policy_flag(self) -> None:
        client = ActuatorClient(
            applications=[AppTarget(name="orders", base_url="http://localhost:8080/actuator")],
        )

        with self.assertRaises(PermissionError):
            client.delete_session("orders", "abc123")

    def test_quartz_selector_rejects_parent_path(self) -> None:
        client = ActuatorClient(
            applications=[AppTarget(name="orders", base_url="http://localhost:8080/actuator")],
        )

        with self.assertRaises(ValueError):
            client.get_quartz("orders", "../jobs")


if __name__ == "__main__":
    unittest.main()

