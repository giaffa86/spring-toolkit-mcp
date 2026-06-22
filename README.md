# Spring Toolkit MCP

Spring Toolkit MCP is a secure-by-default MCP server and CLI for agentic review of
real Spring Boot repositories. It focuses on the practical developer workflow
teams need in production: inspect a Java/Spring codebase, expose safe tools to
an AI agent, and produce review signals around controllers, configuration,
Flyway migrations, JPA, and test opportunities.

The second design goal is simple: **Spring Boot Admin for AI agents**. Human
operators use dashboards; agents need structured tools. Spring Toolkit MCP now
has both workspace inspection and runtime Actuator access, with mutating actions
behind explicit policy flags.

This first version is intentionally dependency-free Python. It can run as:

- an MCP stdio server for clients that support tools/list and tools/call
- a local CLI that prints Markdown or JSON reports
- a Python library for future integrations with Continue, OpenHands, Aider, or CI

## Features

- Detects Maven and Gradle build metadata
- Scans Spring annotations such as controllers, services, repositories, entities,
  mappers, configuration classes, and application entrypoints
- Extracts endpoint mappings and security annotations from Java sources
- Reads `application*.properties`, `application*.yml`, and `application*.yaml`
  while redacting likely secrets
- Scans Flyway migrations for risky operations
- Lists configured Spring Boot Actuator applications
- Reads Actuator endpoint index, health, info, audit events, beans, conditions,
  config properties, mappings, metrics, env, loggers, thread dumps, heap metrics,
  startup steps, scheduled tasks, caches, HTTP exchanges/traces, Flyway and
  Liquibase status, Spring Integration graph, Quartz, sessions, SBOM,
  Prometheus, bounded log files, and heap dump metadata
- Changes logger levels, deletes sessions, and reads sensitive Actuator downloads
  only when explicitly enabled by policy
- Reads Maven Surefire and JaCoCo reports
- Runs Maven or Gradle tests only when explicitly enabled by policy
- Generates pragmatic Markdown review reports
- Suggests MockMvc test skeletons for controllers
- Guards MCP access to configured workspace roots

## How It Works

The server runs as a long-lived process that an MCP client (such as Claude Code)
launches over stdio. It stays alive for the whole client session and answers
JSON-RPC `tools/list` and `tools/call` requests. With an editable install
(`pip install -e .`), the code runs from `src/`, so editing a file and
restarting the client picks up the change with no reinstall.

The tools split into two families with very different requirements:

| Family    | App running? | What it needs                         | Reads / does                                            | Example tools |
|-----------|--------------|---------------------------------------|---------------------------------------------------------|---------------|
| Workspace | **No**       | A project folder on disk, in scope    | Static scan of `.java`, `application.*`, Flyway SQL, build files | `spring_project_summary`, `spring_code_review`, `list_rest_controllers`, `inspect_flyway_migrations` |
| Runtime   | **Yes**      | A live app's Actuator URL configured  | HTTP calls to a running Spring Boot `/actuator` endpoint | `get_health_status`, `get_metrics`, `get_beans`, `get_mappings` |

In short: **static review needs only the folder; live health/metrics need the
app running** with Actuator exposed.

Scope and defaults when nothing is configured:

- Workspace tools can only read the client's current working directory until
  `SPRING_TOOLKIT_ALLOWED_ROOTS` lists more absolute paths.
- Runtime tools see **zero applications** until `SPRING_TOOLKIT_ACTUATOR_BASE_URLS`
  (or `SPRING_TOOLKIT_ACTUATOR_BASE_URL`) is set.
- Mutating actions — logger changes, session deletion, sensitive downloads, and
  test runs — are **off** until their explicit policy flag is enabled (see
  [Runtime Configuration](#runtime-configuration)).

## Quick Start

> The examples below use PowerShell syntax. On Linux/macOS, set environment
> variables with `export NAME=value` instead of `$env:NAME = "value"` and use
> `/` paths instead of `C:\...`. Note that list-valued variables
> (`SPRING_TOOLKIT_ALLOWED_ROOTS`, `SPRING_TOOLKIT_ACTUATOR_BASE_URLS`) are
> always separated by `;` on every platform, not `:`.

From a fresh checkout, install the package in editable mode:

```powershell
python -m pip install -e .
```

Run a Markdown review for the current directory:

```powershell
spring-toolkit review .
```

Run a JSON summary:

```powershell
spring-toolkit summary . --json
```

Start the MCP server:

```powershell
spring-toolkit-mcp
```

## Modes

Workspace mode inspects a local repository:

```powershell
spring-toolkit review C:\work\orders-service
spring-toolkit mockmvc C:\work\orders-service --controller OrderController
```

Runtime mode connects to Spring Boot Actuator:

```powershell
$env:SPRING_TOOLKIT_ACTUATOR_BASE_URLS = "orders=http://localhost:8080/actuator;billing=http://localhost:8081/actuator"
spring-toolkit apps
spring-toolkit actuator --application orders
spring-toolkit health --application orders
spring-toolkit metrics --application orders --metric http.server.requests
spring-toolkit mappings --application orders
```

Full mode combines both in the MCP client: the agent can inspect code, read
runtime health/metrics, read reports, and propose a fix from one tool surface.

By default, workspace MCP tool calls can only inspect the current working
directory. To allow other roots, set `SPRING_TOOLKIT_ALLOWED_ROOTS` to a
semicolon-separated list of absolute paths:

```powershell
$env:SPRING_TOOLKIT_ALLOWED_ROOTS = "C:\work\project-a;C:\work\project-b"
spring-toolkit-mcp
```

When running directly from the checkout without installing, set `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "src"
python -m spring_toolkit_mcp.cli review .
```

## Runtime Configuration

Configure one Actuator app:

```powershell
$env:SPRING_TOOLKIT_ACTUATOR_BASE_URL = "http://localhost:8080/actuator"
```

Configure multiple named apps:

```powershell
$env:SPRING_TOOLKIT_ACTUATOR_BASE_URLS = "orders=http://localhost:8080/actuator;billing=http://localhost:8081/actuator"
```

Optional Basic Auth:

```powershell
$env:SPRING_TOOLKIT_ACTUATOR_USERNAME = "admin"
$env:SPRING_TOOLKIT_ACTUATOR_PASSWORD = "secret"
```

Mutating logger changes are disabled by default:

```powershell
$env:SPRING_TOOLKIT_ENABLE_LOGGER_MUTATION = "true"
```

Sensitive Actuator downloads are disabled by default. Enable them before using
`logfile` or heap dump metadata tools:

```powershell
$env:SPRING_TOOLKIT_ENABLE_ACTUATOR_DOWNLOADS = "true"
```

Session deletion is disabled by default:

```powershell
$env:SPRING_TOOLKIT_ENABLE_SESSION_MUTATION = "true"
```

Build/test execution is also disabled by default:

```powershell
$env:SPRING_TOOLKIT_ENABLE_TEST_RUNS = "true"
spring-toolkit maven-test C:\work\orders-service --test OrderServiceTest
```

Runtime CLI commands mirror the MCP runtime surface: `apps`, `actuator`,
`health`, `info`, `auditevents`, `beans`, `conditions`, `configprops`,
`mappings`, `metrics`, `env`, `loggers`, `set-logger-level`, `threaddump`,
`heap-info`, `heapdump`, `scheduledtasks`, `caches`, `httpexchanges`,
`actuator-flyway`, `liquibase`, `integrationgraph`, `quartz`, `sessions`,
`delete-session`, `startup`, `sbom`, `prometheus`, and `logfile`.

## MCP Tools

`spring_project_summary`

Returns structured metadata for a Spring Boot repository: build files,
dependencies, source roots, components, endpoint mappings, config keys, and
Flyway migrations.

`analyze_project_structure`, `list_rest_controllers`, `list_endpoints`,
`inspect_application_properties`, `inspect_flyway_migrations`

Workspace aliases with names that are easy for agents to select during codebase
inspection.

`spring_code_review`

Returns a pragmatic Markdown or JSON review focused on missing authorization
signals, risky migrations, sensitive configuration, missing test directories,
and common Spring/JPA footguns.

`spring_flyway_risk_scan`

Returns a focused Flyway migration report.

`spring_generate_mockmvc_tests`

Generates starter MockMvc test skeletons for detected controllers.

`list_applications`, `list_actuator_endpoints`, `get_health_status`,
`get_info`, `get_audit_events`, `get_beans`, `get_conditions`,
`get_config_properties`, `get_mappings`, `get_flyway_status`,
`get_liquibase_status`, `get_integration_graph`, `get_metrics`,
`get_env_properties`, `get_loggers`, `get_thread_dump`, `get_startup`,
`get_heap_info`, `get_heap_dump_metadata`, `get_scheduled_tasks`,
`get_cache_stats`, `get_http_traces`, `get_quartz`, `get_sessions`, `get_sbom`,
`get_prometheus`, `get_log_file`

Actuator-backed runtime tools. `get_env_properties` and
`get_config_properties` redact likely secrets. `get_log_file` and
`get_heap_dump_metadata` require `SPRING_TOOLKIT_ENABLE_ACTUATOR_DOWNLOADS=true`.

`change_logger_level`, `delete_session`

Actuator-backed mutations. Logger changes require
`SPRING_TOOLKIT_ENABLE_LOGGER_MUTATION=true`; session deletion requires
`SPRING_TOOLKIT_ENABLE_SESSION_MUTATION=true`.

`run_maven_tests`, `run_gradle_tests`, `run_specific_test`,
`read_surefire_report`, `read_jacoco_report`

Quality-gate tools. Report readers are passive; test runners require
`SPRING_TOOLKIT_ENABLE_TEST_RUNS=true`.

## Demo Flow

User prompt:

```text
Analyze why orders-service is slow before I open the PR.
```

An agent can call:

```text
get_health_status(application="orders")
get_metrics(application="orders", metric="http.server.requests")
get_heap_info(application="orders")
list_endpoints(path="C:\work\orders-service")
read_surefire_report(path="C:\work\orders-service")
spring_code_review(path="C:\work\orders-service")
```

Then it can summarize runtime symptoms, related controller/service code, test
status, migration risk, and concrete next steps.

## MCP Client Configuration Example

```json
{
  "mcpServers": {
    "spring-toolkit": {
      "command": "python",
      "args": ["-m", "spring_toolkit_mcp.server"],
      "env": {
        "SPRING_TOOLKIT_ALLOWED_ROOTS": "C:\\work\\my-spring-app",
        "SPRING_TOOLKIT_ACTUATOR_BASE_URLS": "orders=http://localhost:8080/actuator"
      }
    }
  }
}
```

The server speaks newline-delimited JSON-RPC over stdio, the standard MCP
stdio transport. Any compliant MCP client can launch it with the command and
args above.

## Registering with Claude Code

Claude Code can add the server from the CLI instead of hand-editing config.
From the project directory (after `pip install -e .`):

```bash
claude mcp add spring-toolkit -- python -m spring_toolkit_mcp.server
```

Pass environment variables with `-e` (repeat per variable). Multiple roots or
URLs in one variable are separated by `;` on every platform:

```bash
claude mcp add spring-toolkit \
  -e "SPRING_TOOLKIT_ALLOWED_ROOTS=/work/project-a;/work/project-b" \
  -e SPRING_TOOLKIT_ACTUATOR_BASE_URLS=orders=http://localhost:8080/actuator \
  -- python -m spring_toolkit_mcp.server
```

## Verifying the Server

Confirm the server starts and answers the MCP handshake before wiring it into a
client. Pipe a request to it over stdio:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  | python -m spring_toolkit_mcp.server
```

A successful run prints a single JSON line containing `serverInfo`. To list the
available tools, send `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`
the same way. In Claude Code, `claude mcp list` should report the server as
`✔ Connected`.

## Development

Run tests:

```powershell
python -m unittest discover -s tests
```

The project has no runtime dependencies. That is deliberate for the MVP: agents
can run it in locked-down enterprise environments, and the MCP surface stays
easy to audit.

## Roadmap

- Maven and Gradle test execution tools with explicit allowlists
- SonarQube report ingestion
- PostgreSQL schema introspection
- Spring Security 6 focused checks
- MapStruct and Lombok deeper analysis
- Continue/OpenHands recipes and CI examples

## License

Spring Toolkit MCP is open source software released under the [MIT License](LICENSE).
