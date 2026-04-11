from __future__ import annotations

import json

from growth_engine.cloud.functions import run_decision_job
from growth_engine.config import Settings


class _FallbackCloudRunApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url_map = [("GET", "/healthz"), ("POST", "/api/run")]

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        if method == "GET" and path == "/healthz":
            payload = {"status": "ok", "app": self.settings.app_name}
            return self._respond(start_response, "200 OK", payload)
        if method == "POST" and path == "/api/run":
            length = int(environ.get("CONTENT_LENGTH") or 0)
            body = (
                environ["wsgi.input"].read(length).decode("utf-8") if length else "{}"
            )
            payload = json.loads(body or "{}")
            result = run_decision_job(payload, self.settings)
            return self._respond(start_response, "200 OK", result)
        return self._respond(
            start_response,
            "404 Not Found",
            {"error": "Not found"},
        )

    def _respond(self, start_response, status: str, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        start_response(
            status,
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]


def create_app(settings: Settings | None = None):
    effective_settings = settings or Settings.load()
    try:
        from flask import Flask, jsonify, request
    except ModuleNotFoundError:
        return _FallbackCloudRunApp(effective_settings)

    app = Flask(__name__)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "app": effective_settings.app_name})

    @app.post("/api/run")
    def run():
        payload = request.get_json(force=True, silent=False)
        return jsonify(run_decision_job(payload, effective_settings))

    return app
