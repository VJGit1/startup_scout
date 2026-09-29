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
from fastapi import FastAPI

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
