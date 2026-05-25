"""
RepoSage — FastAPI application entrypoint.
Bootstraps the HTTP server with CORS, health checks, and route inclusion.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router

app = FastAPI(
    title="RepoSage API",
    description="Autonomous GitHub repository health agent — multi-agent pipeline with real-time SSE streaming.",
    version="1.0.0",
)

# CORS — allow the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://frontend:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok", "service": "reposage-api"}


@app.get("/")
async def root() -> dict:
    return {"message": "RepoSage API — see /docs for OpenAPI spec"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
