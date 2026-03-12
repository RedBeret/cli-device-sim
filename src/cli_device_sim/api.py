from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from cli_device_sim.logging_utils import log_event
from cli_device_sim.models import MutateResponse


def create_app(runtime) -> FastAPI:
    app = FastAPI(title="cli-device-sim", version="0.1.0")
    logger = logging.getLogger("cli_device_sim.api")

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        log_event(
            logger,
            logging.INFO,
            "HTTP request handled",
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    @app.get("/healthz")
    def healthz():
        payload = runtime.health_payload()
        status_code = 200 if payload["status"] == "ok" else 503
        return JSONResponse(payload, status_code=status_code)

    @app.get("/state")
    def state():
        return runtime.repository.get_state_response()

    @app.get("/running-config")
    def running_config():
        return PlainTextResponse(runtime.repository.render_snapshot("running"))

    @app.post("/reset", response_model=MutateResponse)
    def reset():
        mutation = runtime.repository.reset_to_defaults()
        runtime.repository.append_audit(
            actor="api/reset",
            event_type="api.reset",
            success=True,
            details={"status": mutation.status},
        )
        return MutateResponse(status=mutation.status, message=mutation.message, state=runtime.repository.get_state_response())

    @app.post("/inject-drift", response_model=MutateResponse)
    def inject_drift():
        mutation = runtime.repository.inject_drift()
        runtime.repository.append_audit(
            actor="api/inject-drift",
            event_type="api.inject-drift",
            success=True,
            details={"status": mutation.status},
        )
        return MutateResponse(status=mutation.status, message=mutation.message, state=runtime.repository.get_state_response())

    return app

