from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .analyzer import analyze_flyway_migrations, analyze_project, generate_mockmvc_tests, generate_review
from .quality import read_jacoco_report, read_surefire_report, run_gradle_tests, run_maven_tests
from .runtime import ActuatorClient


JSON = dict[str, Any]


TOOLS: dict[str, dict[str, Any]] = {
    "spring_project_summary": {
        "description": "Analyze a Spring Boot project and return structured project metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Project directory to analyze. Defaults to the server working directory.",
                }
            },
        },
    },
    "analyze_project_structure": {
        "description": "Alias for spring_project_summary, optimized for agent planning.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Project directory to analyze."}},
        },
    },
    "list_rest_controllers": {
        "description": "List detected Spring MVC/WebFlux controllers.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Project directory to inspect."}},
        },
    },
    "list_endpoints": {
        "description": "List detected REST endpoints from local source code.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Project directory to inspect."}},
        },
    },
    "inspect_application_properties": {
        "description": "Read Spring application properties/YAML with sensitive values redacted.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Project directory to inspect."}},
        },
    },
    "inspect_flyway_migrations": {
        "description": "Inspect local Flyway migrations and risk warnings.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Project directory to inspect."}},
        },
    },
    "spring_code_review": {
        "description": "Generate a pragmatic Spring Boot code review report.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory to review."},
                "format": {"type": "string", "enum": ["markdown", "json"], "default": "markdown"},
            },
        },
    },
    "spring_flyway_risk_scan": {
        "description": "Scan Flyway SQL migrations for risky operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory to scan."},
                "format": {"type": "string", "enum": ["markdown", "json"], "default": "json"},
            },
        },
    },
    "spring_generate_mockmvc_tests": {
        "description": "Generate starter MockMvc test skeletons for detected Spring controllers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory to inspect."},
                "controller": {"type": "string", "description": "Optional controller class name."},
            },
        },
    },
    "generate_mockmvc_test": {
        "description": "Alias for spring_generate_mockmvc_tests.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory to inspect."},
                "controller": {"type": "string", "description": "Optional controller class name."},
            },
        },
    },
    "read_surefire_report": {
        "description": "Read Maven Surefire XML test reports from target/surefire-reports.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Project directory to inspect."}},
        },
    },
    "read_jacoco_report": {
        "description": "Read JaCoCo XML coverage report from target/site/jacoco/jacoco.xml.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Project directory to inspect."}},
        },
    },
    "run_maven_tests": {
        "description": "Run Maven tests when SPRING_TOOLKIT_ENABLE_TEST_RUNS=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory."},
                "test": {"type": "string", "description": "Optional -Dtest value."},
                "extra_args": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "run_gradle_tests": {
        "description": "Run Gradle tests when SPRING_TOOLKIT_ENABLE_TEST_RUNS=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory."},
                "test": {"type": "string", "description": "Optional --tests value."},
                "extra_args": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "run_specific_test": {
        "description": "Run one Maven or Gradle test when SPRING_TOOLKIT_ENABLE_TEST_RUNS=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory."},
                "build_tool": {"type": "string", "enum": ["maven", "gradle"], "default": "maven"},
                "test": {"type": "string", "description": "Test selector."},
            },
            "required": ["test"],
        },
    },
    "list_applications": {
        "description": "List configured Actuator applications.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "get_health_status": {
        "description": "Read /actuator/health for an application.",
        "inputSchema": {"type": "object", "properties": {"application": {"type": "string"}}},
    },
    "get_info": {
        "description": "Read /actuator/info for an application.",
        "inputSchema": {"type": "object", "properties": {"application": {"type": "string"}}},
    },
    "get_metrics": {
        "description": "Read /actuator/metrics or one metric.",
        "inputSchema": {
            "type": "object",
            "properties": {"application": {"type": "string"}, "metric": {"type": "string"}},
        },
    },
    "get_env_properties": {
        "description": "Read /actuator/env with sensitive values redacted.",
        "inputSchema": {
            "type": "object",
            "properties": {"application": {"type": "string"}, "pattern": {"type": "string"}},
        },
    },
    "get_loggers": {
        "description": "Read /actuator/loggers or one logger.",
        "inputSchema": {
            "type": "object",
            "properties": {"application": {"type": "string"}, "logger": {"type": "string"}},
        },
    },
    "change_logger_level": {
        "description": "Change an Actuator logger level when explicitly enabled by policy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "application": {"type": "string"},
                "logger": {"type": "string"},
                "level": {"type": "string", "description": "TRACE, DEBUG, INFO, WARN, ERROR, FATAL, OFF, or NULL."},
            },
            "required": ["logger", "level"],
        },
    },
    "get_thread_dump": {
        "description": "Read /actuator/threaddump.",
        "inputSchema": {"type": "object", "properties": {"application": {"type": "string"}}},
    },
    "get_heap_info": {
        "description": "Read JVM memory metrics from Actuator.",
        "inputSchema": {"type": "object", "properties": {"application": {"type": "string"}}},
    },
    "get_scheduled_tasks": {
        "description": "Read /actuator/scheduledtasks.",
        "inputSchema": {"type": "object", "properties": {"application": {"type": "string"}}},
    },
    "get_cache_stats": {
        "description": "Read /actuator/caches.",
        "inputSchema": {"type": "object", "properties": {"application": {"type": "string"}}},
    },
    "get_http_traces": {
        "description": "Read /actuator/httpexchanges or /actuator/httptrace.",
        "inputSchema": {"type": "object", "properties": {"application": {"type": "string"}}},
    },
}


def main() -> int:
    server = MCPServer()
    server.serve()
    return 0


class MCPServer:
    def __init__(self, cwd: str | Path | None = None, writer: Callable[[JSON], None] | None = None) -> None:
        self.cwd = Path(cwd or os.getcwd()).resolve()
        self.allowed_roots = allowed_roots(self.cwd)
        self.writer = writer or write_message

    def serve(self) -> None:
        while True:
            message = read_message(sys.stdin.buffer)
            if message is None:
                break
            response = self.handle(message)
            if response is not None:
                self.writer(response)

    def handle(self, message: JSON) -> JSON | None:
        method = message.get("method")
        request_id = message.get("id")

        try:
            if method == "initialize":
                return response(request_id, self.initialize_result())
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return response(request_id, {})
            if method == "tools/list":
                return response(request_id, {"tools": list_tools()})
            if method == "tools/call":
                params = message.get("params") or {}
                return response(request_id, self.call_tool(params))
            if request_id is None:
                return None
            return error_response(request_id, -32601, f"Unsupported method: {method}")
        except Exception as exc:
            if request_id is None:
                return None
            return error_response(request_id, -32000, str(exc))

    def initialize_result(self) -> JSON:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "spring-toolkit-mcp", "version": __version__},
        }

    def call_tool(self, params: JSON) -> JSON:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOLS:
            raise ValueError(f"Unknown tool: {name}")

        runtime_tool_names = {
            "list_applications",
            "get_health_status",
            "get_info",
            "get_metrics",
            "get_env_properties",
            "get_loggers",
            "change_logger_level",
            "get_thread_dump",
            "get_heap_info",
            "get_scheduled_tasks",
            "get_cache_stats",
            "get_http_traces",
        }
        if name in runtime_tool_names:
            return text_content(json.dumps(self.call_runtime_tool(name, arguments), indent=2))

        path = self.resolve_allowed_path(arguments.get("path", "."))

        if name in {"spring_project_summary", "analyze_project_structure"}:
            return text_content(json.dumps(analyze_project(path), indent=2))
        if name == "list_rest_controllers":
            summary = analyze_project(path)
            controllers = [component for component in summary["components"] if component["kind"] == "controller"]
            return text_content(json.dumps({"controllers": controllers}, indent=2))
        if name == "list_endpoints":
            return text_content(json.dumps({"endpoints": analyze_project(path)["endpoints"]}, indent=2))
        if name == "inspect_application_properties":
            return text_content(json.dumps({"configuration": analyze_project(path)["configuration"]}, indent=2))
        if name in {"inspect_flyway_migrations", "spring_flyway_risk_scan"}:
            migrations = analyze_flyway_migrations(path)
            if arguments.get("format") == "markdown":
                return text_content(format_flyway_markdown(migrations))
            return text_content(json.dumps({"migrations": migrations}, indent=2))
        if name == "spring_code_review":
            output = arguments.get("format", "markdown")
            result = generate_review(path, output=output)
            text = json.dumps(result, indent=2) if output == "json" else str(result)
            return text_content(text)
        if name in {"spring_generate_mockmvc_tests", "generate_mockmvc_test"}:
            result = generate_mockmvc_tests(path, arguments.get("controller"))
            return text_content(json.dumps(result, indent=2))
        if name == "read_surefire_report":
            return text_content(json.dumps(read_surefire_report(path), indent=2))
        if name == "read_jacoco_report":
            return text_content(json.dumps(read_jacoco_report(path), indent=2))
        if name == "run_maven_tests":
            return text_content(json.dumps(run_maven_tests(path, arguments.get("test"), arguments.get("extra_args")), indent=2))
        if name == "run_gradle_tests":
            return text_content(json.dumps(run_gradle_tests(path, arguments.get("test"), arguments.get("extra_args")), indent=2))
        if name == "run_specific_test":
            build_tool = arguments.get("build_tool", "maven")
            if build_tool == "gradle":
                result = run_gradle_tests(path, arguments.get("test"))
            else:
                result = run_maven_tests(path, arguments.get("test"))
            return text_content(json.dumps(result, indent=2))

        raise ValueError(f"Unhandled tool: {name}")

    def call_runtime_tool(self, name: str, arguments: JSON) -> Any:
        client = ActuatorClient.from_env()
        application = arguments.get("application")
        if name == "list_applications":
            return client.list_applications()
        if name == "get_health_status":
            return client.get_health_status(application)
        if name == "get_info":
            return client.get_info(application)
        if name == "get_metrics":
            return client.get_metrics(application, arguments.get("metric"))
        if name == "get_env_properties":
            return client.get_env_properties(application, arguments.get("pattern"))
        if name == "get_loggers":
            return client.get_loggers(application, arguments.get("logger"))
        if name == "change_logger_level":
            return client.change_logger_level(application, arguments["logger"], arguments.get("level"))
        if name == "get_thread_dump":
            return client.get_thread_dump(application)
        if name == "get_heap_info":
            return client.get_heap_info(application)
        if name == "get_scheduled_tasks":
            return client.get_scheduled_tasks(application)
        if name == "get_cache_stats":
            return client.get_cache_stats(application)
        if name == "get_http_traces":
            return client.get_http_traces(application)
        raise ValueError(f"Unhandled runtime tool: {name}")

    def resolve_allowed_path(self, requested: str | Path) -> Path:
        path = Path(requested)
        if not path.is_absolute():
            path = self.cwd / path
        resolved = path.expanduser().resolve()
        for allowed in self.allowed_roots:
            if resolved == allowed or allowed in resolved.parents:
                return resolved
        allowed_list = ", ".join(str(root) for root in self.allowed_roots)
        raise PermissionError(f"Path is outside allowed roots: {resolved}. Allowed roots: {allowed_list}")


def allowed_roots(default_root: Path) -> list[Path]:
    env_value = os.environ.get("SPRING_TOOLKIT_ALLOWED_ROOTS", "")
    roots = [default_root.resolve()]
    for raw in env_value.split(";"):
        if raw.strip():
            roots.append(Path(raw).expanduser().resolve())
    deduped = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return deduped


def list_tools() -> list[JSON]:
    return [{"name": name, **definition} for name, definition in TOOLS.items()]


def text_content(text: str) -> JSON:
    return {"content": [{"type": "text", "text": text}]}


def response(request_id: Any, result: JSON) -> JSON:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, code: int, message: str) -> JSON:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def read_message(stream: Any) -> JSON | None:
    first = stream.readline()
    if not first:
        return None
    if first.strip().startswith(b"{"):
        return json.loads(first.decode("utf-8"))

    headers = {}
    line = first
    while line and line not in (b"\r\n", b"\n"):
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.lower()] = value.strip()
        line = stream.readline()

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        return None
    body = stream.read(content_length)
    return json.loads(body.decode("utf-8"))


def write_message(message: JSON) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def format_flyway_markdown(migrations: list[dict[str, Any]]) -> str:
    lines = ["# Flyway Risk Scan", ""]
    if not migrations:
        lines.append("No Flyway migrations detected.")
        return "\n".join(lines) + "\n"

    for migration in migrations:
        lines.append(f"## {migration['path']}")
        if migration["warnings"]:
            for warning in migration["warnings"]:
                lines.append(f"- [{warning['code']}] {warning['message']}")
        else:
            lines.append("- No MVP risk warnings detected.")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
