from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spring_toolkit_mcp.cli import main


class CliTests(unittest.TestCase):
    def test_new_runtime_command_routes_to_client(self) -> None:
        class FakeClient:
            def get_mappings(self, application: str | None = None) -> dict[str, object]:
                return {"application": application, "contexts": {}}

        output = io.StringIO()

        with patch("spring_toolkit_mcp.cli.ActuatorClient.from_env", return_value=FakeClient()):
            with patch("sys.stdout", output):
                exit_code = main(["mappings", "--application", "orders"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"application": "orders", "contexts": {}})


if __name__ == "__main__":
    unittest.main()
