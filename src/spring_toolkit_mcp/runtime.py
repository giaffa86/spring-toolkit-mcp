from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote


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
    ) -> None:
        self.applications = applications or load_applications()
        self.timeout_seconds = timeout_seconds
        self.enable_logger_mutation = enable_logger_mutation

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ActuatorClient":
        env = env or os.environ
        timeout = float(env.get("SPRING_TOOLKIT_ACTUATOR_TIMEOUT", "10"))
        mutate = env.get("SPRING_TOOLKIT_ENABLE_LOGGER_MUTATION", "").lower() in {"1", "true", "yes"}
        return cls(load_applications(env), timeout_seconds=timeout, enable_logger_mutation=mutate)

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

    def get_info(self, application: str | None = None) -> Any:
        return self.get(application, "info")

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

    def get(self, application: str | None, endpoint: str) -> Any:
        return self.request(application, endpoint, method="GET")

    def request(self, application: str | None, endpoint: str, method: str, body: dict[str, Any] | None = None) -> Any:
        app = self.resolve_application(application)
        url = f"{app.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
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
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Actuator HTTP {exc.code} for {url}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Actuator request failed for {url}: {exc.reason}") from exc

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

