from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .analyzer import analyze_flyway_migrations, analyze_project, generate_mockmvc_tests, generate_review
from .quality import read_jacoco_report, read_surefire_report, run_gradle_tests, run_maven_tests
from .runtime import ActuatorClient
from .server import format_flyway_markdown


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = args.func(args)
    if payload is not None:
        print(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spring-toolkit",
        description="Analyze and review Spring Boot projects for agentic developer workflows.",
    )
    subparsers = parser.add_subparsers(required=True)

    summary = subparsers.add_parser("summary", help="Print a structured project summary.")
    summary.add_argument("path", nargs="?", default=".", type=Path)
    summary.add_argument("--json", action="store_true", help="Print JSON instead of a compact text summary.")
    summary.set_defaults(func=summary_command)

    review = subparsers.add_parser("review", help="Print a Spring-focused code review.")
    review.add_argument("path", nargs="?", default=".", type=Path)
    review.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    review.set_defaults(func=review_command)

    flyway = subparsers.add_parser("flyway", help="Scan Flyway migrations.")
    flyway.add_argument("path", nargs="?", default=".", type=Path)
    flyway.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    flyway.set_defaults(func=flyway_command)

    tests = subparsers.add_parser("mockmvc", help="Generate MockMvc test skeletons.")
    tests.add_argument("path", nargs="?", default=".", type=Path)
    tests.add_argument("--controller", help="Limit output to one controller class name.")
    tests.set_defaults(func=mockmvc_command)

    surefire = subparsers.add_parser("surefire", help="Read Maven Surefire XML reports.")
    surefire.add_argument("path", nargs="?", default=".", type=Path)
    surefire.set_defaults(func=surefire_command)

    jacoco = subparsers.add_parser("jacoco", help="Read JaCoCo XML coverage report.")
    jacoco.add_argument("path", nargs="?", default=".", type=Path)
    jacoco.set_defaults(func=jacoco_command)

    maven_test = subparsers.add_parser("maven-test", help="Run Maven tests when enabled by policy.")
    maven_test.add_argument("path", nargs="?", default=".", type=Path)
    maven_test.add_argument("--test", help="Optional -Dtest selector.")
    maven_test.add_argument("extra_args", nargs="*", help="Extra Maven arguments.")
    maven_test.set_defaults(func=maven_test_command)

    gradle_test = subparsers.add_parser("gradle-test", help="Run Gradle tests when enabled by policy.")
    gradle_test.add_argument("path", nargs="?", default=".", type=Path)
    gradle_test.add_argument("--test", help="Optional --tests selector.")
    gradle_test.add_argument("extra_args", nargs="*", help="Extra Gradle arguments.")
    gradle_test.set_defaults(func=gradle_test_command)

    apps = subparsers.add_parser("apps", help="List configured Actuator applications.")
    apps.set_defaults(func=apps_command)

    health = subparsers.add_parser("health", help="Read Actuator health.")
    health.add_argument("--application", help="Configured application name.")
    health.set_defaults(func=health_command)

    metrics = subparsers.add_parser("metrics", help="Read Actuator metrics.")
    metrics.add_argument("--application", help="Configured application name.")
    metrics.add_argument("--metric", help="Optional metric name, for example http.server.requests.")
    metrics.set_defaults(func=metrics_command)

    loggers = subparsers.add_parser("loggers", help="Read Actuator loggers.")
    loggers.add_argument("--application", help="Configured application name.")
    loggers.add_argument("--logger", help="Optional logger name.")
    loggers.set_defaults(func=loggers_command)

    set_logger = subparsers.add_parser("set-logger-level", help="Change an Actuator logger level when enabled.")
    set_logger.add_argument("--application", help="Configured application name.")
    set_logger.add_argument("--logger", required=True, help="Logger name.")
    set_logger.add_argument("--level", required=True, help="TRACE, DEBUG, INFO, WARN, ERROR, FATAL, OFF, or NULL.")
    set_logger.set_defaults(func=set_logger_level_command)

    runtime_parser(subparsers, "actuator", "Read the Actuator endpoint index.", actuator_command)
    runtime_parser(subparsers, "info", "Read Actuator info.", info_command)
    env = runtime_parser(subparsers, "env", "Read Actuator env with sensitive values redacted.", env_command)
    env.add_argument("--pattern", help="Optional property-name filter.")

    runtime_parser(subparsers, "threaddump", "Read Actuator thread dump.", threaddump_command)
    runtime_parser(subparsers, "heap-info", "Read JVM heap metrics.", heap_info_command)
    runtime_parser(subparsers, "scheduledtasks", "Read Actuator scheduled tasks.", scheduledtasks_command)
    runtime_parser(subparsers, "caches", "Read Actuator caches.", caches_command)
    runtime_parser(subparsers, "httpexchanges", "Read Actuator HTTP exchanges/traces.", httpexchanges_command)
    runtime_parser(subparsers, "beans", "Read Actuator beans.", beans_command)
    runtime_parser(subparsers, "conditions", "Read Actuator conditions.", conditions_command)
    runtime_parser(subparsers, "configprops", "Read Actuator config properties.", configprops_command)
    runtime_parser(subparsers, "mappings", "Read Actuator mappings.", mappings_command)
    runtime_parser(subparsers, "actuator-flyway", "Read Actuator Flyway status.", actuator_flyway_command)
    runtime_parser(subparsers, "liquibase", "Read Actuator Liquibase status.", liquibase_command)
    runtime_parser(subparsers, "integrationgraph", "Read Actuator integration graph.", integrationgraph_command)
    runtime_parser(subparsers, "startup", "Read Actuator startup steps.", startup_command)

    auditevents = runtime_parser(subparsers, "auditevents", "Read Actuator audit events.", auditevents_command)
    auditevents.add_argument("--principal", help="Optional principal filter.")
    auditevents.add_argument("--after", help="Optional ISO-8601 timestamp filter.")
    auditevents.add_argument("--type", dest="event_type", help="Optional audit event type filter.")

    quartz = runtime_parser(subparsers, "quartz", "Read Actuator quartz data.", quartz_command)
    quartz.add_argument("--selector", help="Optional quartz sub-path such as jobs or triggers.")

    sessions = runtime_parser(subparsers, "sessions", "Read Actuator sessions.", sessions_command)
    sessions.add_argument("--session-id", help="Optional session id.")

    delete_session = runtime_parser(subparsers, "delete-session", "Delete an Actuator session when enabled.", delete_session_command)
    delete_session.add_argument("--session-id", required=True, help="Session id to delete.")

    sbom = runtime_parser(subparsers, "sbom", "Read Actuator SBOM data.", sbom_command)
    sbom.add_argument("--sbom-id", help="Optional SBOM id.")

    prometheus = runtime_parser(subparsers, "prometheus", "Read Actuator Prometheus text.", prometheus_command)
    prometheus.add_argument("--max-chars", type=int, default=20000, help="Maximum characters to return.")

    logfile = runtime_parser(subparsers, "logfile", "Read Actuator logfile text when enabled.", logfile_command)
    logfile.add_argument("--max-chars", type=int, default=20000, help="Maximum characters to return.")

    runtime_parser(subparsers, "heapdump", "Read heapdump response metadata when enabled.", heapdump_command)

    return parser


def runtime_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    func: Any,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("--application", help="Configured application name.")
    parser.set_defaults(func=func)
    return parser


def summary_command(args: argparse.Namespace) -> str:
    summary = analyze_project(args.path)
    if args.json:
        return json.dumps(summary, indent=2)

    lines = [
        f"Project: {summary['root']}",
        f"Build: {summary['build'].get('tool') or 'unknown'}",
        f"Source roots: {', '.join(summary['source_roots']) or 'none'}",
        f"Test roots: {', '.join(summary['test_roots']) or 'none'}",
        f"Endpoints: {summary['health']['endpoint_count']}",
        f"Components: {summary['component_counts']}",
        f"Flyway migrations: {len(summary['flyway'])}",
    ]
    return "\n".join(lines)


def review_command(args: argparse.Namespace) -> str:
    result = generate_review(args.path, output="json" if args.json else "markdown")
    return json.dumps(result, indent=2) if isinstance(result, dict) else result


def flyway_command(args: argparse.Namespace) -> str:
    migrations = analyze_flyway_migrations(args.path)
    if args.json:
        return json.dumps({"migrations": migrations}, indent=2)
    return format_flyway_markdown(migrations)


def mockmvc_command(args: argparse.Namespace) -> str:
    return json.dumps(generate_mockmvc_tests(args.path, args.controller), indent=2)


def surefire_command(args: argparse.Namespace) -> str:
    return json.dumps(read_surefire_report(args.path), indent=2)


def jacoco_command(args: argparse.Namespace) -> str:
    return json.dumps(read_jacoco_report(args.path), indent=2)


def maven_test_command(args: argparse.Namespace) -> str:
    return json.dumps(run_maven_tests(args.path, args.test, args.extra_args), indent=2)


def gradle_test_command(args: argparse.Namespace) -> str:
    return json.dumps(run_gradle_tests(args.path, args.test, args.extra_args), indent=2)


def apps_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().list_applications(), indent=2)


def health_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_health_status(args.application), indent=2)


def metrics_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_metrics(args.application, args.metric), indent=2)


def loggers_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_loggers(args.application, args.logger), indent=2)


def set_logger_level_command(args: argparse.Namespace) -> str:
    return json.dumps(
        ActuatorClient.from_env().change_logger_level(args.application, args.logger, args.level),
        indent=2,
    )


def actuator_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().list_actuator_endpoints(args.application), indent=2)


def info_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_info(args.application), indent=2)


def env_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_env_properties(args.application, args.pattern), indent=2)


def threaddump_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_thread_dump(args.application), indent=2)


def heap_info_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_heap_info(args.application), indent=2)


def scheduledtasks_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_scheduled_tasks(args.application), indent=2)


def caches_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_cache_stats(args.application), indent=2)


def httpexchanges_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_http_traces(args.application), indent=2)


def beans_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_beans(args.application), indent=2)


def conditions_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_conditions(args.application), indent=2)


def configprops_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_config_properties(args.application), indent=2)


def mappings_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_mappings(args.application), indent=2)


def actuator_flyway_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_flyway_status(args.application), indent=2)


def liquibase_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_liquibase_status(args.application), indent=2)


def integrationgraph_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_integration_graph(args.application), indent=2)


def startup_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_startup(args.application), indent=2)


def auditevents_command(args: argparse.Namespace) -> str:
    return json.dumps(
        ActuatorClient.from_env().get_audit_events(
            args.application,
            args.principal,
            args.after,
            args.event_type,
        ),
        indent=2,
    )


def quartz_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_quartz(args.application, args.selector), indent=2)


def sessions_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_sessions(args.application, args.session_id), indent=2)


def delete_session_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().delete_session(args.application, args.session_id), indent=2)


def sbom_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_sbom(args.application, args.sbom_id), indent=2)


def prometheus_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_prometheus(args.application, args.max_chars), indent=2)


def logfile_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_log_file(args.application, args.max_chars), indent=2)


def heapdump_command(args: argparse.Namespace) -> str:
    return json.dumps(ActuatorClient.from_env().get_heap_dump_metadata(args.application), indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
