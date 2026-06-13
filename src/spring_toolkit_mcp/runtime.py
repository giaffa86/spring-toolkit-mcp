from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote, urlencode


SECRET_HINTS = (
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

LOGGER_LEVELS = {"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "OFF", "NULL"}
TRUE_VALUES = {"1", "true", "yes"}
DOWNLOADS_FLAG = "SPRING_TOOLKIT_ENABLE_ACTUATOR_DOWNLOADS"
SESSION_MUTATION_FLAG = "SPRING_TOOLKIT_ENABLE_SESSION_MUTATION"


@dataclass(frozen=True)
class AppTarget:
    name: str
    base_url: str
    username: str | None = None
    password: str | None = None


class ActuatorClient:
    def __init__(
        self,
        applications: list[AppTarget] | None = None,
        timeout_seconds: float = 10,
        enable_logger_mutation: bool = False,
        enable_actuator_downloads: bool = False,
        enable_session_mutation: bool = False,
    ) -> None:
        self.applications = applications or load_applications()
        self.timeout_seconds = timeout_seconds
        self.enable_logger_mutation = enable_logger_mutation
        self.enable_actuator_downloads = enable_actuator_downloads
        self.enable_session_mutation = enable_session_mutation

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ActuatorClient":
        env = env or os.environ
        timeout = float(env.get("SPRING_TOOLKIT_ACTUATOR_TIMEOUT", "10"))
        mutate = env.get("SPRING_TOOLKIT_ENABLE_LOGGER_MUTATION", "").lower() in TRUE_VALUES
        downloads = env.get(DOWNLOADS_FLAG, "").lower() in TRUE_VALUES
        session_mutation = env.get(SESSION_MUTATION_FLAG, "").lower() in TRUE_VALUES
        return cls(
            load_applications(env),
            timeout_seconds=timeout,
            enable_logger_mutation=mutate,
            enable_actuator_downloads=downloads,
            enable_session_mutation=session_mutation,
        )

    def list_applications(self) -> dict[str, Any]:
        return {
            "applications": [
                {"name": app.name, "base_url": app.base_url, "has_basic_auth": bool(app.username)}
                for app in self.applications
            ],
            "configured": bool(self.applications),
        }

    def get_health_status(self, application: str | None = None) -> Any:
        return self.get(application, "health")

    def list_actuator_endpoints(self, application: str | None = None) -> Any:
        return self.get(application, "")

    def get_info(self, application: str | None = None) -> Any:
        return self.get(application, "info")

    def get_audit_events(
        self,
        application: str | None = None,
        principal: str | None = None,
        after: str | None = None,
        event_type: str | None = None,
    ) -> Any:
        return self.get(
            application,
            "auditevents",
            query_params={"principal": principal, "after": after, "type": event_type},
        )

    def get_beans(self, application: str | None = None) -> Any:
        return self.get(application, "beans")

    def get_conditions(self, application: str | None = None) -> Any:
        return self.get(application, "conditions")

    def get_config_properties(self, application: str | None = None) -> Any:
        return redact_actuator_payload(self.get(application, "configprops"))

    def get_mappings(self, application: str | None = None) -> Any:
        return self.get(application, "mappings")

    def get_flyway_status(self, application: str | None = None) -> Any:
        return self.get(application, "flyway")

    def get_liquibase_status(self, application: str | None = None) -> Any:
        return self.get(application, "liquibase")

    def get_integration_graph(self, application: str | None = None) -> Any:
        return self.get(application, "integrationgraph")

    def get_metrics(self, application: str | None = None, metric: str | None = None) -> Any:
        endpoint = "metrics" if not metric else f"metrics/{quote(metric, safe='.')}"
        return self.get(application, endpoint)

    def get_env_properties(self, application: str | None = None, pattern: str | None = None) -> Any:
        payload = redact_actuator_payload(self.get(application, "env"))
        if pattern:
            return filter_env_payload(payload, pattern)
        return payload

    def get_loggers(self, application: str | None = None, logger: str | None = None) -> Any:
        endpoint = "loggers" if not logger else f"loggers/{quote(logger, safe='.')}"
        return self.get(application, endpoint)

    def change_logger_level(self, application: str | None, logger: str, level: str | None) -> Any:
        normalized_level = "NULL" if level is None else level.upper()
        if normalized_level not in LOGGER_LEVELS:
            raise ValueError(f"Unsupported logger level: {level}")
        if not self.enable_logger_mutation:
            raise PermissionError(
                "Logger mutation is disabled. Set SPRING_TOOLKIT_ENABLE_LOGGER_MUTATION=true to allow it."
            )
        body = {"configuredLevel": None if normalized_level == "NULL" else normalized_level}
        return self.request(application, f"loggers/{quote(logger, safe='.')}", method="POST", body=body)

    def get_thread_dump(self, application: str | None = None) -> Any:
        return self.get(application, "threaddump")

    def get_startup(self, application: str | None = None) -> Any:
        return self.get(application, "startup")

    def get_heap_info(self, application: str | None = None) -> dict[str, Any]:
        metrics = {}
        for metric in ("jvm.memory.used", "jvm.memory.committed", "jvm.memory.max"):
            try:
                metrics[metric] = self.get_metrics(application, metric)
            except RuntimeError as exc:
                metrics[metric] = {"error": str(exc)}
        return {"metrics": metrics}

    def get_scheduled_tasks(self, application: str | None = None) -> Any:
        return self.get(application, "scheduledtasks")

    def get_cache_stats(self, application: str | None = None) -> Any:
        return self.get(application, "caches")

    def get_http_traces(self, application: str | None = None) -> Any:
        try:
            return self.get(application, "httpexchanges")
        except RuntimeError:
            return self.get(application, "httptrace")

    def get_quartz(self, application: str | None = None, selector: str | None = None) -> Any:
        endpoint = append_endpoint_selector("quartz", selector)
        return self.get(application, endpoint)

    def get_sessions(self, application: str | None = None, session_id: str | None = None) -> Any:
        endpoint = "sessions" if not session_id else f"sessions/{quote(session_id, safe='')}"
        return self.get(application, endpoint)

    def delete_session(self, application: str | None, session_id: str) -> Any:
        if not self.enable_session_mutation:
            raise PermissionError(
                f"Session mutation is disabled. Set {SESSION_MUTATION_FLAG}=true to allow it."
            )
        return self.request(application, f"sessions/{quote(session_id, safe='')}", method="DELETE")

    def get_sbom(self, application: str | None = None, sbom_id: str | None = None) -> Any:
        endpoint = "sbom" if not sbom_id else f"sbom/{quote(sbom_id, safe='')}"
        return self.get(application, endpoint)

    def get_prometheus(self, application: str | None = None, max_chars: int = 20000) -> dict[str, Any]:
        return self.request_text(application, "prometheus", accept="text/plain", max_chars=max_chars)

    def get_log_file(self, application: str | None = None, max_chars: int = 20000) -> dict[str, Any]:
        self.require_downloads_enabled("logfile")
        return self.request_text(application, "logfile", accept="text/plain", max_chars=max_chars)

    def get_heap_dump_metadata(self, application: str | None = None) -> dict[str, Any]:
        self.require_downloads_enabled("heapdump")
        return self.request_metadata(application, "heapdump", method="HEAD")

    def get(
        self,
        application: str | None,
        endpoint: str,
        query_params: Mapping[str, str | None] | None = None,
    ) -> Any:
        return self.request(application, endpoint, method="GET", query_params=query_params)

    def request(
        self,
        application: str | None,
        endpoint: str,
        method: str,
        body: dict[str, Any] | None = None,
        query_params: Mapping[str, str | None] | None = None,
        accept: str = "application/json",
    ) -> Any:
        app = self.resolve_application(application)
        url = build_endpoint_url(app.base_url, endpoint, query_params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", accept)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if app.username and app.password:
            token = base64.b64encode(f"{app.username}:{app.password}".encode("utf-8")).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
                if not raw:
                    return {"status": response.status}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {
                        "status": response.status,
                        "content_type": response.headers.get("Content-Type"),
                        "content": raw,
                    }
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Actuator HTTP {exc.code} for {url}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Actuator request failed for {url}: {exc.reason}") from exc

    def request_text(
        self,
        application: str | None,
        endpoint: str,
        accept: str,
        max_chars: int,
        query_params: Mapping[str, str | None] | None = None,
    ) -> dict[str, Any]:
        if max_chars < 1:
            raise ValueError("max_chars must be greater than zero")

        app = self.resolve_application(application)
        url = build_endpoint_url(app.base_url, endpoint, query_params)
        request = urllib.request.Request(url, method="GET")
        request.add_header("Accept", accept)
        if app.username and app.password:
            token = base64.b64encode(f"{app.username}:{app.password}".encode("utf-8")).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(max_chars + 1)
                text = raw.decode("utf-8", errors="replace")
                truncated = len(text) > max_chars
                return {
                    "status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "content": text[:max_chars],
                    "truncated": truncated,
                    "max_chars": max_chars,
                }
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Actuator HTTP {exc.code} for {url}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Actuator request failed for {url}: {exc.reason}") from exc

    def request_metadata(
        self,
        application: str | None,
        endpoint: str,
        method: str,
        query_params: Mapping[str, str | None] | None = None,
    ) -> dict[str, Any]:
        app = self.resolve_application(application)
        url = build_endpoint_url(app.base_url, endpoint, query_params)
        request = urllib.request.Request(url, method=method)
        request.add_header("Accept", "*/*")
        if app.username and app.password:
            token = base64.b64encode(f"{app.username}:{app.password}".encode("utf-8")).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return {"status": response.status, "url": url, "headers": dict(response.headers.items())}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Actuator HTTP {exc.code} for {url}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Actuator request failed for {url}: {exc.reason}") from exc

    def require_downloads_enabled(self, endpoint: str) -> None:
        if not self.enable_actuator_downloads:
            raise PermissionError(
                f"Actuator {endpoint} access is disabled. Set {DOWNLOADS_FLAG}=true to allow it."
            )

    def resolve_application(self, application: str | None) -> AppTarget:
        if not self.applications:
            raise RuntimeError(
                "No Actuator applications configured. Set SPRING_TOOLKIT_ACTUATOR_BASE_URL or "
                "SPRING_TOOLKIT_ACTUATOR_BASE_URLS."
            )
        if application is None:
            return self.applications[0]
        for app in self.applications:
            if app.name == application:
                return app
        names = ", ".join(app.name for app in self.applications)
        raise ValueError(f"Unknown application: {application}. Configured applications: {names}")


def load_applications(env: Mapping[str, str] | None = None) -> list[AppTarget]:
    env = env or os.environ
    raw = env.get("SPRING_TOOLKIT_ACTUATOR_BASE_URLS") or env.get("SPRING_TOOLKIT_ACTUATOR_BASE_URL") or ""
    username = env.get("SPRING_TOOLKIT_ACTUATOR_USERNAME")
    password = env.get("SPRING_TOOLKIT_ACTUATOR_PASSWORD")
    apps = []

    for index, entry in enumerate(part.strip() for part in raw.split(";") if part.strip()):
        name, base_url = parse_application_entry(entry, index)
        apps.append(AppTarget(name=name, base_url=normalize_actuator_url(base_url), username=username, password=password))

    return apps


def parse_application_entry(entry: str, index: int) -> tuple[str, str]:
    if "=" in entry and not entry.lower().startswith(("http://", "https://")):
        name, url = entry.split("=", 1)
        return name.strip(), url.strip()
    return ("default" if index == 0 else f"app-{index + 1}"), entry


def normalize_actuator_url(base_url: str) -> str:
    return base_url.rstrip("/")


def build_endpoint_url(
    base_url: str,
    endpoint: str,
    query_params: Mapping[str, str | None] | None = None,
) -> str:
    base = base_url.rstrip("/")
    endpoint_path = endpoint.strip("/")
    url = base if not endpoint_path else f"{base}/{endpoint_path}"
    query = urlencode({key: value for key, value in (query_params or {}).items() if value is not None})
    return f"{url}?{query}" if query else url


def append_endpoint_selector(endpoint: str, selector: str | None) -> str:
    if not selector:
        return endpoint
    cleaned = selector.strip().strip("/")
    if not cleaned:
        return endpoint

    segments = cleaned.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"Unsafe Actuator endpoint selector: {selector}")
    return f"{endpoint}/{'/'.join(quote(segment, safe='') for segment in segments)}"


def redact_actuator_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            if is_secret_key(key):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_actuator_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_actuator_payload(item) for item in payload]
    return payload


def filter_env_payload(payload: Any, pattern: str) -> Any:
    if not isinstance(payload, dict):
        return payload
    lowered = pattern.lower()
    filtered = {**payload}
    property_sources = []
    for source in payload.get("propertySources", []):
        properties = source.get("properties", {})
        matching = {key: value for key, value in properties.items() if lowered in key.lower()}
        if matching:
            property_sources.append({**source, "properties": matching})
    filtered["propertySources"] = property_sources
    return filtered


def is_secret_key(key: str) -> bool:
    normalized = key.lower()
    return any(hint in normalized for hint in SECRET_HINTS)

