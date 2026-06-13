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


if __name__ == "__main__":
    raise SystemExit(main())
