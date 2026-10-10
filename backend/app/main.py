"""Minimal Nestwatch API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .clients.open_wearables import OpenWearablesClient, OpenWearablesError
from .config import Settings
from .routes.debug import router as debug_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http_client:
        app.state.open_wearables = OpenWearablesClient(app.state.settings, http_client)
        yield


app = FastAPI(title="Nestwatch", debug=False, lifespan=lifespan)
app.state.settings = Settings()
app.include_router(debug_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(OpenWearablesError)
async def handle_open_wearables_error(
    request: Request, exc: OpenWearablesError
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error during %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
