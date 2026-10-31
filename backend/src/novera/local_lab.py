"""Single-origin, loopback-only Novera research laboratory.

The React static build and the reviewed synthetic FastAPI routes are served
from the same process. No login, market feeds, secrets, production deployment
or financial provider connectivity is provided by this entry point.
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from novera.demo_api import create_app

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


def default_frontend_directory() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_local_app(*, frontend_directory: Path | None = None) -> FastAPI:
    """Factory for local static assets + API. Do not mount untrusted directories."""
    directory = (
        default_frontend_directory() if frontend_directory is None else Path(frontend_directory)
    )
    if not directory.is_absolute() or not (directory / "index.html").is_file():
        raise RuntimeError(
            "Novera Lab frontend build not found. In frontend/, run "
            "'npm ci --ignore-scripts' then 'npm run build' before starting the local lab."
        )
    if directory.is_symlink() or (directory / "index.html").is_symlink():
        raise RuntimeError("Novera Lab does not serve linked frontend directories")

    app = create_app()

    @app.middleware("http")
    async def browser_policy(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response

    # Must be registered AFTER the explicit API routes.
    app.mount("/", StaticFiles(directory=str(directory), html=True), name="lab-ui")
    return app


def main() -> None:
    """One local address for the offline UI and synthetic HTTP API."""
    app = create_local_app()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
