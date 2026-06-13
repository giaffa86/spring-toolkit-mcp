from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SKIP_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".mvn",
    ".settings",
    "build",
    "node_modules",
    "out",
    "target",
}

SPRING_COMPONENT_ANNOTATIONS = {
    "RestController": "controller",
    "Controller": "controller",
    "Service": "service",
    "Repository": "repository",
    "Entity": "entity",
    "Mapper": "mapper",
    "Configuration": "configuration",
    "SpringBootApplication": "application",
    "ControllerAdvice": "advice",
    "Component": "component",
}

MAPPING_ANNOTATIONS = (
    "RequestMapping",
    "GetMapping",
    "PostMapping",
    "PutMapping",
    "PatchMapping",
    "DeleteMapping",
)

SECURITY_ANNOTATIONS = (
    "PreAuthorize",
    "PostAuthorize",
    "Secured",
    "RolesAllowed",
    "PermitAll",
    "DenyAll",
)

SECRET_KEY_HINTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private-key",
    "private_key",
    "client-secret",
    "apikey",
    "api-key",
)

RISKY_SQL_PATTERNS = {
    "drop_table": re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    "drop_column": re.compile(r"\bALTER\s+TABLE\b[\s\S]*?\bDROP\s+COLUMN\b", re.IGNORECASE),
    "truncate": re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
    "delete_without_where": re.compile(r"\bDELETE\s+FROM\s+\w+\s*;", re.IGNORECASE),
    "update_without_where": re.compile(r"\bUPDATE\s+\w+\s+SET\b(?![\s\S]*?\bWHERE\b)", re.IGNORECASE),
    "create_index_non_concurrent": re.compile(r"\bCREATE\s+INDEX\b(?!\s+CONCURRENTLY)", re.IGNORECASE),
}


@dataclass(frozen=True)
class JavaComponent:
    path: str
    package: str | None
    name: str
    kind: str
    annotations: list[str]
    mappings: list[dict[str, Any]]
    security_annotations: list[str]


def analyze_project(root: str | Path) -> dict[str, Any]:
    """Analyze a Spring Boot project and return JSON-serializable metadata."""

    project_root = Path(root).expanduser().resolve()
    if not project_root.exists():
        raise FileNotFoundError(f"Path does not exist: {project_root}")
    if not project_root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {project_root}")

    java_files = list(iter_files(project_root, "*.java"))
    components = [component for path in java_files if (component := analyze_java_file(project_root, path))]
    config_files = list(iter_config_files(project_root))
    migrations = analyze_flyway_migrations(project_root)

    return {
        "root": str(project_root),
        "build": analyze_build(project_root),
        "source_roots": discover_source_roots(project_root),
        "test_roots": discover_test_roots(project_root),
        "components": [component.__dict__ for component in components],
        "component_counts": count_by_kind(components),
        "endpoints": collect_endpoints(components),
        "configuration": [analyze_config_file(project_root, path) for path in config_files],
        "flyway": migrations,
        "health": project_health(project_root, components, migrations),
    }


def analyze_build(root: Path) -> dict[str, Any]:
    pom = root / "pom.xml"
    gradle = root / "build.gradle"
    gradle_kts = root / "build.gradle.kts"

    result: dict[str, Any] = {
        "tool": None,
        "files": [],
        "project": {},
        "dependencies": [],
        "plugins": [],
    }

    if pom.exists():
        parsed = parse_pom(pom)
        result.update(parsed)
        result["tool"] = "maven"
        result["files"].append(relative(root, pom))

    for build_file in (gradle, gradle_kts):
        if build_file.exists():
            parsed = parse_gradle(build_file)
            if result["tool"] is None:
                result["tool"] = "gradle"
            elif result["tool"] != "gradle":
                result["tool"] = "mixed"
            result["files"].append(relative(root, build_file))
            result["dependencies"].extend(parsed["dependencies"])
            result["plugins"].extend(parsed["plugins"])

    return result


def parse_pom(path: Path) -> dict[str, Any]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except ET.ParseError as exc:
        return {"project": {"parse_error": str(exc)}, "dependencies": [], "plugins": []}

    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"

    def find_text(parent: ET.Element, tag: str) -> str | None:
        element = parent.find(f"{namespace}{tag}")
        if element is not None and element.text:
            return element.text.strip()
        return None

    project = {
        "group_id": find_text(root, "groupId"),
        "artifact_id": find_text(root, "artifactId"),
        "version": find_text(root, "version"),
    }

    parent = root.find(f"{namespace}parent")
    if parent is not None:
        project["parent"] = {
            "group_id": find_text(parent, "groupId"),
            "artifact_id": find_text(parent, "artifactId"),
            "version": find_text(parent, "version"),
        }
        project["group_id"] = project["group_id"] or project["parent"]["group_id"]
        project["version"] = project["version"] or project["parent"]["version"]

    dependencies = []
    for dependency in root.findall(f".//{namespace}dependency"):
        dependencies.append(
            {
                "group_id": find_text(dependency, "groupId"),
                "artifact_id": find_text(dependency, "artifactId"),
                "scope": find_text(dependency, "scope"),
            }
        )

    plugins = []
    for plugin in root.findall(f".//{namespace}plugin"):
        artifact_id = find_text(plugin, "artifactId")
        group_id = find_text(plugin, "groupId")
        if artifact_id:
            plugins.append({"group_id": group_id, "artifact_id": artifact_id})

    return {"project": project, "dependencies": dependencies, "plugins": plugins}


def parse_gradle(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    dependencies = []
    plugins = []

    for match in re.finditer(
        r"(?P<scope>implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly)\s*(?:\(|\s)\s*[\"'](?P<gav>[^\"']+)[\"']",
        text,
    ):
        dependencies.append({"scope": match.group("scope"), "gav": match.group("gav")})

    for match in re.finditer(r"id\s*(?:\(|\s)\s*[\"'](?P<plugin>[^\"']+)[\"']", text):
        plugins.append({"id": match.group("plugin")})

    return {"dependencies": dependencies, "plugins": plugins}


def discover_source_roots(root: Path) -> list[str]:
    candidates = [
        root / "src" / "main" / "java",
        root / "src" / "main" / "kotlin",
    ]
    return [relative(root, path) for path in candidates if path.exists()]


def discover_test_roots(root: Path) -> list[str]:
    candidates = [
        root / "src" / "test" / "java",
        root / "src" / "test" / "kotlin",
    ]
    return [relative(root, path) for path in candidates if path.exists()]


def analyze_java_file(project_root: Path, path: Path) -> JavaComponent | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    annotations = extract_annotations(text)
    component_kinds = [SPRING_COMPONENT_ANNOTATIONS[name] for name in annotations if name in SPRING_COMPONENT_ANNOTATIONS]
    mappings = extract_mappings(text)

    if not component_kinds and not mappings:
        return None

    class_match = re.search(r"\b(class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    package_match = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)\s*;", text, re.MULTILINE)
    security_annotations = [name for name in annotations if name in SECURITY_ANNOTATIONS]

    return JavaComponent(
        path=relative(project_root, path),
        package=package_match.group(1) if package_match else None,
        name=class_match.group(2) if class_match else path.stem,
        kind=component_kinds[0] if component_kinds else "endpoint",
        annotations=annotations,
        mappings=mappings,
        security_annotations=security_annotations,
    )


def extract_annotations(text: str) -> list[str]:
    seen = []
    for match in re.finditer(r"@([A-Za-z_][A-Za-z0-9_]*)", text):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def extract_mappings(text: str) -> list[dict[str, Any]]:
    mappings = []
    for annotation in MAPPING_ANNOTATIONS:
        pattern = re.compile(rf"@{annotation}\s*(?:\((?P<args>[^)]*)\))?", re.MULTILINE | re.DOTALL)
        for match in pattern.finditer(text):
            args = match.group("args") or ""
            mappings.append(
                {
                    "annotation": annotation,
                    "paths": extract_string_literals(args) or ["/"],
                    "methods": extract_http_methods(annotation, args),
                }
            )
    return mappings


def extract_string_literals(text: str) -> list[str]:
    values = []
    for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'', text):
        values.append(match.group(1) or match.group(2))
    return values


def extract_http_methods(annotation: str, args: str) -> list[str]:
    direct = {
        "GetMapping": "GET",
        "PostMapping": "POST",
        "PutMapping": "PUT",
        "PatchMapping": "PATCH",
        "DeleteMapping": "DELETE",
    }
    if annotation in direct:
        return [direct[annotation]]

    methods = []
    for match in re.finditer(r"RequestMethod\.([A-Z]+)", args):
        methods.append(match.group(1))
    return methods or ["ANY"]


def collect_endpoints(components: Iterable[JavaComponent]) -> list[dict[str, Any]]:
    endpoints = []
    for component in components:
        if not component.mappings:
            continue
        class_paths = ["/"]
        method_mappings = []
        for mapping in component.mappings:
            if mapping["annotation"] == "RequestMapping":
                class_paths = mapping["paths"] or ["/"]
            else:
                method_mappings.append(mapping)

        if not method_mappings:
            method_mappings = component.mappings

        for mapping in method_mappings:
            for class_path in class_paths:
                for method_path in mapping["paths"]:
                    endpoints.append(
                        {
                            "component": component.name,
                            "path": join_url_paths(class_path, method_path),
                            "methods": mapping["methods"],
                            "source": component.path,
                            "secured": bool(component.security_annotations),
                        }
                    )
    return endpoints


def join_url_paths(left: str, right: str) -> str:
    if left == "/" and right == "/":
        return "/"
    joined = "/" + "/".join(part.strip("/") for part in (left, right) if part and part != "/")
    return re.sub(r"/+", "/", joined)


def iter_config_files(root: Path) -> Iterable[Path]:
    for pattern in ("application*.properties", "application*.yml", "application*.yaml"):
        yield from iter_files(root, pattern)


def analyze_config_file(root: Path, path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    entries = parse_properties(path) if suffix == ".properties" else parse_yaml_like(path)
    return {
        "path": relative(root, path),
        "entries": [
            {
                "key": key,
                "value": redact_value(key, value),
                "redacted": is_secret_key(key),
            }
            for key, value in entries
        ],
    }


def parse_properties(path: Path) -> list[tuple[str, str]]:
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        separator = "=" if "=" in stripped else ":"
        if separator not in stripped:
            continue
        key, value = stripped.split(separator, 1)
        entries.append((key.strip(), value.strip()))
    return entries


def parse_yaml_like(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped or stripped.startswith("-"):
            continue
        key, value = stripped.split(":", 1)
        key = key.strip().strip("\"'")
        value = value.strip().strip("\"'")

        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))

        if value:
            full_key = ".".join(item[1] for item in stack)
            entries.append((full_key, value))
            stack.pop()
    return entries


def redact_value(key: str, value: str) -> str:
    if is_secret_key(key):
        return "<redacted>"
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.lower()
    return any(hint in normalized for hint in SECRET_KEY_HINTS)


def analyze_flyway_migrations(root: str | Path) -> list[dict[str, Any]]:
    project_root = Path(root).expanduser().resolve()
    migrations = []
    migration_roots = [
        project_root / "src" / "main" / "resources" / "db" / "migration",
        project_root / "src" / "test" / "resources" / "db" / "migration",
    ]
    for migration_root in migration_roots:
        if not migration_root.exists():
            continue
        for path in sorted(iter_files(migration_root, "*.sql")):
            text = path.read_text(encoding="utf-8", errors="replace")
            migrations.append(
                {
                    "path": relative(project_root, path),
                    "version": extract_flyway_version(path.name),
                    "description": extract_flyway_description(path.name),
                    "warnings": sql_warnings(text),
                }
            )
    return migrations


def extract_flyway_version(filename: str) -> str | None:
    match = re.match(r"V(.+?)__", filename, re.IGNORECASE)
    return match.group(1) if match else None


def extract_flyway_description(filename: str) -> str | None:
    match = re.match(r"V.+?__(.+)\.sql$", filename, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).replace("_", " ")


def sql_warnings(sql: str) -> list[dict[str, str]]:
    warnings = []
    for code, pattern in RISKY_SQL_PATTERNS.items():
        if pattern.search(sql):
            warnings.append({"code": code, "message": SQL_WARNING_MESSAGES[code]})
    return warnings


SQL_WARNING_MESSAGES = {
    "drop_table": "Drops a table. Verify backups, compatibility, and rollback strategy.",
    "drop_column": "Drops a column. Check application compatibility and data retention requirements.",
    "truncate": "Truncates data. Confirm this cannot remove production data unexpectedly.",
    "delete_without_where": "Deletes rows without a WHERE clause.",
    "update_without_where": "Updates rows without a WHERE clause.",
    "create_index_non_concurrent": "Creates an index without CONCURRENTLY, which can block writes on PostgreSQL.",
}


def project_health(root: Path, components: list[JavaComponent], migrations: list[dict[str, Any]]) -> dict[str, Any]:
    endpoints = collect_endpoints(components)
    unsecured = [endpoint for endpoint in endpoints if not endpoint["secured"]]
    has_tests = bool(discover_test_roots(root))
    risky_migrations = [migration for migration in migrations if migration["warnings"]]
    dependencies = analyze_build(root).get("dependencies", [])

    return {
        "has_tests": has_tests,
        "endpoint_count": len(endpoints),
        "unsecured_endpoint_count": len(unsecured),
        "risky_migration_count": len(risky_migrations),
        "uses_spring_security": dependency_mentions(dependencies, "spring-boot-starter-security"),
        "uses_jpa": dependency_mentions(dependencies, "spring-boot-starter-data-jpa"),
        "uses_mapstruct": dependency_mentions(dependencies, "mapstruct"),
        "uses_lombok": dependency_mentions(dependencies, "lombok"),
    }


def dependency_mentions(dependencies: list[dict[str, Any]], needle: str) -> bool:
    return any(needle in json.dumps(dependency).lower() for dependency in dependencies)


def generate_review(root: str | Path, output: str = "markdown") -> str | dict[str, Any]:
    summary = analyze_project(root)
    findings = build_findings(summary)
    if output == "json":
        return {"summary": summary, "findings": findings}
    return format_review_markdown(summary, findings)


def build_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for endpoint in summary["endpoints"]:
        if not endpoint["secured"]:
            findings.append(
                {
                    "severity": "medium",
                    "category": "security",
                    "title": "Endpoint has no local authorization annotation",
                    "detail": f"{endpoint['methods']} {endpoint['path']} in {endpoint['source']}",
                    "source": endpoint["source"],
                }
            )

    for migration in summary["flyway"]:
        for warning in migration["warnings"]:
            findings.append(
                {
                    "severity": "high" if warning["code"] in {"drop_table", "truncate"} else "medium",
                    "category": "database",
                    "title": warning["message"],
                    "detail": migration["path"],
                    "source": migration["path"],
                }
            )

    if not summary["test_roots"]:
        findings.append(
            {
                "severity": "medium",
                "category": "testing",
                "title": "No test source root detected",
                "detail": "Expected src/test/java or src/test/kotlin.",
                "source": None,
            }
        )

    for config_file in summary["configuration"]:
        for entry in config_file["entries"]:
            if entry["redacted"]:
                findings.append(
                    {
                        "severity": "low",
                        "category": "configuration",
                        "title": "Sensitive configuration key detected",
                        "detail": f"{entry['key']} in {config_file['path']}",
                        "source": config_file["path"],
                    }
                )

    entity_count = summary["component_counts"].get("entity", 0)
    if entity_count and not summary["health"]["uses_jpa"]:
        findings.append(
            {
                "severity": "low",
                "category": "persistence",
                "title": "JPA entities detected but JPA starter was not found",
                "detail": "Check build metadata or custom persistence setup.",
                "source": None,
            }
        )

    return findings


def format_review_markdown(summary: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    build = summary["build"]
    project = build.get("project", {})
    title = project.get("artifact_id") or Path(summary["root"]).name
    lines = [
        f"# Spring Toolkit Review: {title}",
        "",
        "## Snapshot",
        "",
        f"- Build tool: {build.get('tool') or 'unknown'}",
        f"- Source roots: {', '.join(summary['source_roots']) or 'none detected'}",
        f"- Test roots: {', '.join(summary['test_roots']) or 'none detected'}",
        f"- Endpoints: {summary['health']['endpoint_count']}",
        f"- Components: {format_counts(summary['component_counts'])}",
        f"- Flyway migrations: {len(summary['flyway'])}",
        "",
        "## Findings",
        "",
    ]

    if not findings:
        lines.append("No findings detected by the static MVP checks.")
    else:
        for finding in sorted(findings, key=finding_sort_key):
            source = f" ({finding['source']})" if finding.get("source") else ""
            lines.append(f"- [{finding['severity'].upper()}] {finding['title']}{source}")
            lines.append(f"  Detail: {finding['detail']}")

    lines.extend(["", "## Detected Endpoints", ""])
    if summary["endpoints"]:
        for endpoint in summary["endpoints"]:
            methods = ",".join(endpoint["methods"])
            secured = "secured" if endpoint["secured"] else "no local auth annotation"
            lines.append(f"- {methods} {endpoint['path']} -> {endpoint['component']} ({secured})")
    else:
        lines.append("No controller mappings detected.")

    lines.extend(["", "## Next Actions", ""])
    lines.extend(next_actions(summary, findings))
    return "\n".join(lines) + "\n"


def next_actions(summary: dict[str, Any], findings: list[dict[str, Any]]) -> list[str]:
    actions = []
    categories = {finding["category"] for finding in findings}
    if "security" in categories:
        actions.append("- Add or verify method/class-level authorization checks for exposed endpoints.")
    if "database" in categories:
        actions.append("- Review Flyway migration blast radius and add rollback or deployment notes.")
    if "testing" in categories:
        actions.append("- Add focused MockMvc or slice tests for controller behavior.")
    if summary["health"]["uses_mapstruct"]:
        actions.append("- Add mapper tests for null handling and enum/value conversions.")
    if not actions:
        actions.append("- Expand checks with project-specific architectural rules.")
    return actions


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none detected"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))


def finding_sort_key(finding: dict[str, Any]) -> tuple[int, str]:
    priority = {"high": 0, "medium": 1, "low": 2}
    return priority.get(finding["severity"], 99), finding["title"]


def generate_mockmvc_tests(root: str | Path, controller: str | None = None) -> dict[str, Any]:
    summary = analyze_project(root)
    controllers = [
        component
        for component in summary["components"]
        if component["kind"] == "controller" and (controller is None or component["name"] == controller)
    ]
    return {
        "controllers": [
            {
                "name": component["name"],
                "source": component["path"],
                "suggested_test_path": suggested_test_path(component),
                "skeleton": mockmvc_skeleton(component),
            }
            for component in controllers
        ]
    }


def suggested_test_path(component: dict[str, Any]) -> str:
    package_path = (component.get("package") or "").replace(".", "/")
    return f"src/test/java/{package_path}/{component['name']}Test.java" if package_path else f"src/test/java/{component['name']}Test.java"


def mockmvc_skeleton(component: dict[str, Any]) -> str:
    package_line = f"package {component['package']};\n\n" if component.get("package") else ""
    first_mapping, path = first_concrete_mapping(component)
    method = first_mapping["methods"][0].lower()
    request_builder = {
        "get": "get",
        "post": "post",
        "put": "put",
        "patch": "patch",
        "delete": "delete",
        "any": "get",
    }.get(method, "get")
    class_name = f"{component['name']}Test"
    return (
        f"{package_line}"
        "import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;\n"
        "import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;\n\n"
        "import org.junit.jupiter.api.Test;\n"
        "import org.springframework.beans.factory.annotation.Autowired;\n"
        "import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;\n"
        "import org.springframework.test.web.servlet.MockMvc;\n\n"
        f"@WebMvcTest({component['name']}.class)\n"
        f"class {class_name} {{\n\n"
        "    @Autowired\n"
        "    private MockMvc mockMvc;\n\n"
        "    @Test\n"
        "    void shouldReturnExpectedResponse() throws Exception {\n"
        f"        mockMvc.perform({request_builder}(\"{path}\"))\n"
        "            .andExpect(status().isOk());\n"
        "    }\n"
        "}\n"
    )


def first_concrete_mapping(component: dict[str, Any]) -> tuple[dict[str, Any], str]:
    mappings = component.get("mappings") or [{"annotation": "GetMapping", "paths": ["/"], "methods": ["GET"]}]
    class_paths = ["/"]
    method_mappings = []

    for mapping in mappings:
        if mapping["annotation"] == "RequestMapping":
            class_paths = mapping.get("paths") or ["/"]
        else:
            method_mappings.append(mapping)

    selected = method_mappings[0] if method_mappings else mappings[0]
    selected_path = selected.get("paths", ["/"])[0]
    if method_mappings:
        return selected, join_url_paths(class_paths[0], selected_path)
    return selected, selected_path


def count_by_kind(components: Iterable[JavaComponent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for component in components:
        counts[component.kind] = counts.get(component.kind, 0) + 1
    return counts


def iter_files(root: Path, pattern: str) -> Iterable[Path]:
    for path in root.rglob(pattern):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
