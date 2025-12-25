import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from routers import api

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def get_system_downloads_folder():
    """Get the user's system Downloads folder"""
    home = Path.home()

    # Check common Downloads folder locations
    if os.name == "nt":  # Windows
        downloads = home / "Downloads"
    else:  # Linux/Mac
        downloads = home / "Downloads"

    # Create if doesn't exist
    downloads.mkdir(parents=True, exist_ok=True)
    return str(downloads)


app = FastAPI(title="Music Downloader API", version="1.0.0")

# CORS middleware (still useful for API endpoints)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(api.router)


@app.middleware("http")
async def add_root_path(request: Request, call_next):
    root_path = request.headers.get("X-Forwarded-Prefix", "")
    request.scope["root_path"] = root_path
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the frontend index.html"""
    template_name = "index.html"
    return templates.TemplateResponse(template_name, context={"request": request})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)
