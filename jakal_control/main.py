from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import AppConfig, load_config
from .database import Database
from .enums import TriggerSource
from .exceptions import ControlError
from .schemas import DashboardView, JobPayload, JobView, LogTailView, RunView, TogglePayload
from .services.control import ControlService
from .services.coordinator import SupervisorCoordinator


class AppContainer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config.db_path)
        self.db.initialize()
        self.control = ControlService(self.db, config)
        self.coordinator = SupervisorCoordinator(self.db, config)


def create_app(config: AppConfig | None = None) -> FastAPI:
    app_config = config or load_config()
    container = AppContainer(app_config)
    web_root = Path(__file__).resolve().parent / "web"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container.coordinator.start()
        try:
            yield
        finally:
            container.coordinator.stop()
            container.coordinator.join(timeout=5)
            container.db.dispose()

    app = FastAPI(title="Jakal Control", lifespan=lifespan)
    app.state.container = container
    app.mount("/static", StaticFiles(directory=web_root), name="static")

    @app.exception_handler(ControlError)
    async def control_error_handler(_: Request, exc: ControlError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=FileResponse)
    async def index() -> FileResponse:
        return FileResponse(web_root / "index.html")

    @app.get("/api/dashboard", response_model=DashboardView)
    async def dashboard(request: Request) -> DashboardView:
        return request.app.state.container.control.get_dashboard()

    @app.post("/api/jobs", response_model=JobView, status_code=status.HTTP_201_CREATED)
    async def create_job(_: Request, payload: JobPayload) -> Response:
        job = container.control.upsert_job(payload)
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=job.model_dump(mode="json"))

    @app.put("/api/jobs/{job_id}")
    async def update_job(job_id: str, payload: JobPayload) -> Response:
        job = container.control.upsert_job(payload, job_id=job_id)
        return JSONResponse(content=job.model_dump(mode="json"))

    @app.delete("/api/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_job(job_id: str) -> Response:
        container.control.delete_job(job_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.put("/api/jobs/{job_id}/enabled")
    async def set_job_enabled(job_id: str, payload: TogglePayload) -> Response:
        job = container.control.set_job_enabled(job_id, payload.enabled)
        return JSONResponse(content=job.model_dump(mode="json"))

    @app.post("/api/jobs/{job_id}/run")
    async def run_job(job_id: str) -> Response:
        run = container.control.queue_run(job_id, trigger_source=TriggerSource.MANUAL)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=run.model_dump(mode="json"))

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> Response:
        run = container.control.cancel_run(run_id)
        return JSONResponse(content=run.model_dump(mode="json"))

    @app.post("/api/runs/{run_id}/retry")
    async def retry_run(run_id: str) -> Response:
        run = container.control.retry_run(run_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=run.model_dump(mode="json"))

    @app.get("/api/runs/{run_id}/log", response_model=LogTailView)
    async def run_log(run_id: str) -> LogTailView:
        return container.control.get_run_log(run_id)

    return app


def run() -> None:
    config = load_config()
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level="info")
