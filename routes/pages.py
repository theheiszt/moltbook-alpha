"""
Moltbook Alpha — Static and Interactive HTML Pages and Assets.
"""

import json
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from config import INDEX_HTML_PATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent

router = APIRouter(tags=["Pages"])


def create_pages_router() -> APIRouter:
    return router


@router.get("/", response_class=HTMLResponse)
@router.get("/index.html", response_class=HTMLResponse)
def index():
    if INDEX_HTML_PATH.exists():
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Moltbook Alpha API</h1>"


@router.get("/dashboard", response_class=HTMLResponse)
@router.get("/dashboard.html", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the real-time Moltbook Alpha traffic & operations dashboard."""
    dashboard_path = PROJECT_ROOT / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(content=dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard application file not found.</h1>", status_code=404)


@router.get("/jobs", response_class=HTMLResponse)
@router.get("/jobs.html", response_class=HTMLResponse)
def serve_jobs():
    """Serves the Agent Jobs & Bounties board."""
    jobs_path = PROJECT_ROOT / "jobs.html"
    if jobs_path.exists():
        return HTMLResponse(content=jobs_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Jobs application file not found.</h1>", status_code=404)


@router.get("/nfts", response_class=HTMLResponse)
@router.get("/nfts.html", response_class=HTMLResponse)
def serve_nfts():
    """Serves the Molt Alpha DEMS NFT collection portal."""
    nfts_path = PROJECT_ROOT / "nfts.html"
    if nfts_path.exists():
        return HTMLResponse(content=nfts_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>NFT application file not found.</h1>", status_code=404)


@router.get("/sample.json")
def serve_sample_json():
    """Serves sample.json for agent and developer quickstarts."""
    sample_path = PROJECT_ROOT / "sample.json"
    if sample_path.exists():
        return JSONResponse(content=json.loads(sample_path.read_text(encoding="utf-8")))
    return JSONResponse(content={"error": "sample.json not found"}, status_code=404)
