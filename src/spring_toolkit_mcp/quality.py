from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def read_surefire_report(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).expanduser().resolve()
    report_dir = project_root / "target" / "surefire-reports"
    reports = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    for path in sorted(report_dir.glob("TEST-*.xml")) if report_dir.exists() else []:
        parsed = parse_surefire_xml(project_root, path)
        reports.append(parsed)
        for key in totals:
            totals[key] += parsed[key]

    return {"report_dir": str(report_dir), "totals": totals, "reports": reports, "found": bool(reports)}


def parse_surefire_xml(project_root: Path, path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return empty_suite(project_root, path)

    cases = []
    for case in suite.findall("testcase"):
        status = "passed"
        if case.find("failure") is not None:
            status = "failure"
        elif case.find("error") is not None:
            status = "error"
        elif case.find("skipped") is not None:
            status = "skipped"
        cases.append(
            {
                "class_name": case.attrib.get("classname"),
                "name": case.attrib.get("name"),
                "time": float(case.attrib.get("time", "0") or 0),
                "status": status,
            }
        )

    return {
        "path": relative(project_root, path),
        "name": suite.attrib.get("name"),
        "tests": int(float(suite.attrib.get("tests", "0") or 0)),
        "failures": int(float(suite.attrib.get("failures", "0") or 0)),
        "errors": int(float(suite.attrib.get("errors", "0") or 0)),
        "skipped": int(float(suite.attrib.get("skipped", "0") or 0)),
        "time": float(suite.attrib.get("time", "0") or 0),
        "cases": cases,
    }


def empty_suite(project_root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": relative(project_root, path),
        "name": None,
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "time": 0,
        "cases": [],
    }


def read_jacoco_report(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).expanduser().resolve()
    report_path = project_root / "target" / "site" / "jacoco" / "jacoco.xml"
    if not report_path.exists():
        return {"found": False, "path": str(report_path), "counters": []}

    tree = ET.parse(report_path)
    counters = []
    for counter in tree.getroot().findall("counter"):
        missed = int(counter.attrib.get("missed", "0"))
        covered = int(counter.attrib.get("covered", "0"))
        total = missed + covered
        counters.append(
            {
                "type": counter.attrib.get("type"),
                "missed": missed,
                "covered": covered,
                "coverage": round(covered / total, 4) if total else None,
            }
        )
    return {"found": True, "path": relative(project_root, report_path), "counters": counters}


def run_maven_tests(root: str | Path, test: str | None = None, extra_args: list[str] | None = None) -> dict[str, Any]:
    project_root = Path(root).expanduser().resolve()
    command = maven_command(project_root, test, extra_args)
    return run_build_command(project_root, command, "SPRING_TOOLKIT_ENABLE_TEST_RUNS")


def run_gradle_tests(root: str | Path, test: str | None = None, extra_args: list[str] | None = None) -> dict[str, Any]:
    project_root = Path(root).expanduser().resolve()
    command = gradle_command(project_root, test, extra_args)
    return run_build_command(project_root, command, "SPRING_TOOLKIT_ENABLE_TEST_RUNS")


def run_build_command(project_root: Path, command: list[str], env_flag: str) -> dict[str, Any]:
    if os.environ.get(env_flag, "").lower() not in {"1", "true", "yes"}:
        return {
            "ran": False,
            "enabled": False,
            "command": command,
            "message": f"Test execution is disabled. Set {env_flag}=true to allow build commands.",
        }

    timeout = int(os.environ.get("SPRING_TOOLKIT_TEST_TIMEOUT_SECONDS", "600"))
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, timeout=timeout, check=False)
    return {
        "ran": True,
        "enabled": True,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-20000:],
        "stderr": completed.stderr[-20000:],
    }


def maven_command(project_root: Path, test: str | None, extra_args: list[str] | None) -> list[str]:
    executable = str(project_root / "mvnw.cmd") if (project_root / "mvnw.cmd").exists() else "mvn"
    command = [executable, "test"]
    if test:
        command.append(f"-Dtest={test}")
    command.extend(extra_args or [])
    return command


def gradle_command(project_root: Path, test: str | None, extra_args: list[str] | None) -> list[str]:
    executable = str(project_root / "gradlew.bat") if (project_root / "gradlew.bat").exists() else "gradle"
    command = [executable, "test"]
    if test:
        command.append(f"--tests={test}")
    command.extend(extra_args or [])
    return command


def relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")

