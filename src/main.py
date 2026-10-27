"""
FastAPI Backend for the Hybrid n8n + LangGraph Lifestyle Startup PRD Pipeline.
Exposes endpoints for:
- GET  /health
- GET  /api/v1/skills          (Inspect all loaded agentskills.io SKILL.md modules)
- POST /api/v1/stage1/evaluate (Stage 1: Evaluate Reddit posts -> Pick Top 3 -> Return Google Sheets rows)
- POST /api/v1/stage2/generate-prd (Stage 2: Human-approved Google Sheet row -> Generate full Google Doc PRD)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from src.board import (
    find_idea,
    founder_form_values,
    founder_profile_path,
    list_runs,
    load_run,
    output_dir,
    prd_path,
    render_board,
    render_founder_form,
    save_stage1,
    stage2_request_from_idea,
    update_founder_profile,
)
from src.tools.search import fetch_hacker_news_pain_points
from src.graph.stage1_graph import run_stage1_pipeline
from src.graph.stage2_graph import run_stage2_pipeline
from src.models import (
    Stage1EvaluateRequest,
    Stage1EvaluateResponse,
    Stage2PRDRequest,
    Stage2PRDResponse,
)
from src.skill_loader import load_all_skills, load_founder_profile

load_dotenv()

app = FastAPI(
    title="Lifestyle Startup Discovery & PRD Multi-Agent API",
    description=(
        "Hybrid n8n + LangGraph Supervisor backend powered by agentskills.io SKILL.md packages. "
        "Stage 1 evaluates Reddit startup ideas (Bottom-Up TAM, Startup Cost, Competition, Founder Fit) "
        "and picks the Top 3 for Google Sheets. Stage 2 generates a Google Doc PRD (with Kano Model "
        "prioritization, GTM, and Risk Analysis) when an idea is approved in Google Sheets."
    ),
    version="1.0.0",
)


@app.middleware("http")
async def require_api_key(request, call_next):
    """Protect /api/* when API_AUTH_KEY is set. /health stays open for platform probes."""
    expected = os.getenv("API_AUTH_KEY", "").strip()
    if expected and request.url.path.startswith("/api/"):
        provided = request.headers.get("x-api-key", "")
        if provided != expected:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


class ApproveBody(BaseModel):
    idea_id: str
    run: str = ""


class FounderBody(BaseModel):
    name: str = ""
    max_cost: int = 2500
    weekly_hours: int = 20
    technical_skills: str = ""


@app.get("/", response_class=HTMLResponse)
def results_page(run: str = "") -> str:
    directory = output_dir()
    payload = load_run(directory, run or None)
    names = [path.name for path in list_runs(directory)]
    return render_board(payload, run_name=run, runs=names)


@app.post("/fetch-hn")
def fetch_hacker_news() -> Dict[str, Any]:
    """Score two live Hacker News posts and replace the page's latest run."""
    posts = fetch_hacker_news_pain_points(max_posts=2)
    if not posts:
        raise HTTPException(status_code=503, detail="Hacker News returned no posts")
    result = run_stage1_pipeline(
        Stage1EvaluateRequest(posts=posts, source="hn", fetch_live=False)
    )
    directory = output_dir()
    save_stage1(directory, result.model_dump_json(indent=2), result.google_sheets_rows)
    return {
        "ok": True,
        "agent_mode": result.agent_mode,
        "count": result.total_posts_analyzed,
        "urls": [idea.source_reddit_url for idea in result.top_3_ideas],
    }


@app.post("/approve")
def approve_idea(body: ApproveBody) -> Dict[str, Any]:
    directory = output_dir()
    payload = load_run(directory, body.run or None)
    if payload is None:
        raise HTTPException(status_code=404, detail="No scored run to approve")
    idea = find_idea(payload, body.idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found in this run")
    result = run_stage2_pipeline(stage2_request_from_idea(idea))
    path = prd_path(directory, idea.idea_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.google_doc_markdown, encoding="utf-8")
    if idea.rank == 1:
        (directory / "google_doc_prd_top1.md").write_text(result.google_doc_markdown, encoding="utf-8")
    return {"ok": True, "agent_mode": result.agent_mode, "path": str(path)}


@app.get("/founder", response_class=HTMLResponse)
def founder_page() -> str:
    return render_founder_form(founder_form_values(founder_profile_path()))


@app.post("/founder")
def save_founder(body: FounderBody) -> Dict[str, Any]:
    skills = [line.strip() for line in body.technical_skills.splitlines() if line.strip()]
    path = founder_profile_path()
    update_founder_profile(
        path,
        name=body.name.strip() or "Founder",
        max_cost=body.max_cost,
        weekly_hours=body.weekly_hours,
        technical_skills=skills,
    )
    return {"ok": True}


@app.get("/health")
def health_check() -> Dict[str, Any]:
    skills = load_all_skills()
    founder = load_founder_profile()
    return {
        "status": "ok",
        "loaded_skills": list(skills.keys()),
        "founder_profile_name": founder.get("founder", {}).get("name", "Unknown"),
    }


@app.get("/api/v1/skills")
def list_agent_skills() -> List[Dict[str, Any]]:
    """Return metadata for all discovered agentskills.io SKILL.md definitions."""
    skills = load_all_skills()
    return [
        {
            "name": s.name,
            "description": s.description,
            "path": str(s.path),
            "bundled_references": list(s.references.keys()),
        }
        for s in skills.values()
    ]


@app.post("/api/v1/stage1/evaluate", response_model=Stage1EvaluateResponse)
def stage1_evaluate_endpoint(request: Stage1EvaluateRequest) -> Stage1EvaluateResponse:
    """
    Stage 1 Endpoint called by n8n after scraping Reddit posts.
    Orchestrates the Supervisor -> Competitive/TAM Researcher -> Founder-Market Fit -> Startup Evaluator
    and returns ranked ideas, the Top 3 picks, and flattened rows for Google Sheets.
    """
    return run_stage1_pipeline(request)


@app.post("/api/v1/stage2/generate-prd", response_model=Stage2PRDResponse)
def stage2_generate_prd_endpoint(request: Stage2PRDRequest) -> Stage2PRDResponse:
    """
    Stage 2 Endpoint called by n8n when a user changes a row's Approval_Status to 'Approved' in Google Sheets.
    Orchestrates the Supervisor -> Deep Researcher -> PM Agent (Kano Model) -> Risk Analysis Agent
    and returns the complete Google Doc PRD markdown and structured sections.
    """
    return run_stage2_pipeline(request)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("src.main:app", host=host, port=port, reload=True)
