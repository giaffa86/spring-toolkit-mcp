from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spring_toolkit_mcp.server import MCPServer, read_message


class ServerTests(unittest.TestCase):
    def test_lists_tools(self) -> None:
        server = MCPServer(cwd=Path.cwd(), writer=lambda _: None)
        result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(result["id"], 1)
        tool_names = {tool["name"] for tool in result["result"]["tools"]}
        self.assertIn("spring_project_summary", tool_names)
        self.assertIn("spring_code_review", tool_names)
        self.assertIn("get_health_status", tool_names)
        self.assertIn("run_maven_tests", tool_names)
        self.assertIn("get_beans", tool_names)
        self.assertIn("get_mappings", tool_names)
        self.assertIn("get_heap_dump_metadata", tool_names)

    def test_rejects_paths_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            server = MCPServer(cwd=allowed, writer=lambda _: None)
            result = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "spring_project_summary", "arguments": {"path": outside}},
                }
            )

            self.assertIn("error", result)
            self.assertIn("outside allowed roots", result["error"]["message"])

    def test_reads_content_length_framed_message(self) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")
        stream = io.BytesIO(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)

        message = read_message(stream)

        self.assertEqual(message["method"], "ping")

    def test_routes_new_runtime_tool(self) -> None:
        class FakeClient:
            def get_beans(self, application: str | None = None) -> dict[str, object]:
                return {"application": application, "contexts": {}}

        server = MCPServer(cwd=Path.cwd(), writer=lambda _: None)

        with patch("spring_toolkit_mcp.server.ActuatorClient.from_env", return_value=FakeClient()):
            result = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "get_beans", "arguments": {"application": "orders"}},
                }
            )

        payload = json.loads(result["result"]["content"][0]["text"])
        self.assertEqual(payload["application"], "orders")


if __name__ == "__main__":
    unittest.main()
