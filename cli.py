"""
CLI Runner to test and demonstrate the Two-Stage Multi-Agent Pipeline locally.
Runs Stage 1 (Reddit -> Evaluator Top 3 -> Google Sheets CSV/JSON) and
Stage 2 (Approved Top Idea -> Research + PM Kano + Risk Agents -> Google Doc PRD Markdown).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

from src.graph.stage1_graph import run_stage1_pipeline
from src.graph.stage2_graph import run_stage2_pipeline
from src.models import RedditPostInput, Stage1EvaluateRequest, Stage2PRDRequest
from src.skill_loader import load_all_skills

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
SOURCES = ("curated", "hn", "reddit_rss", "all")


def _build_stage1_request(source: str, posts_file: Path | None) -> Stage1EvaluateRequest:
    if posts_file is not None:
        raw = json.loads(posts_file.read_text(encoding="utf-8"))
        posts = [RedditPostInput.model_validate(item) for item in raw]
        return Stage1EvaluateRequest(posts=posts, source=source, fetch_live=False)
    return Stage1EvaluateRequest(posts=[], source=source, fetch_live=source != "curated")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run the lifestyle startup discovery pipeline.")
    parser.add_argument("--source", choices=SOURCES, default="curated")
    parser.add_argument("--posts-file", type=Path, default=None, help="JSON list of pain-point posts.")
    args = parser.parse_args(argv)

    load_dotenv()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    skills = load_all_skills()
    print("=" * 78)
    print("LIFESTYLE STARTUP DISCOVERY & PRD PIPELINE (LangGraph + Agent Skills)")
    print("=" * 78)
    print(f"Loaded {len(skills)} agentskills.io SKILL.md modules: {', '.join(skills.keys())}\n")

    # -------------------------------------------------------------------------
    # STAGE 1: Evaluate pain points -> Pick Top 3 -> Export Google Sheet preview
    # -------------------------------------------------------------------------
    print("[Stage 1] Running Supervisor -> Competitive/TAM Researcher -> Founder Fit -> Evaluator...")
    stage1_req = _build_stage1_request(args.source, args.posts_file)
    stage1_res = run_stage1_pipeline(stage1_req)

    # Save Stage 1 JSON & Google Sheets CSV preview
    stage1_json_path = OUTPUT_DIR / "stage1_evaluated_ideas.json"
    stage1_json_path.write_text(stage1_res.model_dump_json(indent=2), encoding="utf-8")

    csv_path = OUTPUT_DIR / "google_sheets_evaluated_ideas.csv"
    if stage1_res.google_sheets_rows:
        fieldnames = list(stage1_res.google_sheets_rows[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(stage1_res.google_sheets_rows)

    print(
        f"  -> Analyzed {stage1_res.total_posts_analyzed} posts "
        f"(source={stage1_res.source_used}, agent_mode={stage1_res.agent_mode})."
    )
    if stage1_res.node_errors:
        print(f"  -> Node notes: {len(stage1_res.node_errors)}")
    print("  -> Top 3 Lifestyle Startup Ideas selected by Startup Evaluator Agent:")
    for idea in stage1_res.top_3_ideas:
        print(
            f"     #{idea.rank}: {idea.idea_title} | Score: {idea.scores.weighted_total_score}/100 | "
            f"TAM: ${idea.research.tam.bottom_up_tam_usd:,.0f}/yr | "
            f"Startup Cost: ${idea.research.estimated_startup_cost_usd:,.0f} | "
            f"Founder Fit: {idea.founder_fit.founder_fit_score}/10"
        )
    print(f"  -> Saved Google Sheets rows preview to: {csv_path}\n")

    if not stage1_res.top_3_ideas:
        print("Stage 2 skipped: Top 3 is empty. No idea qualified under the founder budget.")
        print(f"  -> Stage 1 results remain at: {stage1_json_path}")
        return

    # -------------------------------------------------------------------------
    # STAGE 2: Simulate Human Approval of #1 Idea in Google Sheets -> Build PRD
    # -------------------------------------------------------------------------
    winner = stage1_res.top_3_ideas[0]
    print(f"[Stage 2] Simulating Google Sheets human approval ('Approved') for #{winner.rank}: {winner.idea_title}...")
    stage2_req = Stage2PRDRequest(
        idea_id=winner.idea_id,
        idea_title=winner.idea_title,
        one_line_pitch=winner.one_line_pitch,
        core_problem=winner.core_problem,
        target_customer=winner.target_customer,
        source_subreddit=winner.source_subreddit,
        source_reddit_title=winner.source_reddit_title,
        source_reddit_url=winner.source_reddit_url,
        bottom_up_tam_summary=winner.research.tam.tam_formula_explanation,
        startup_cost_summary=winner.research.startup_cost_breakdown,
        competitors_summary=", ".join(f"{c.name} ({c.pricing})" for c in winner.research.competitors),
        competitive_wedge=winner.research.competitive_wedge,
        founder_fit_summary=winner.founder_fit.fit_rationale,
        total_score=winner.scores.weighted_total_score,
        founder_fit_score=winner.founder_fit.founder_fit_score,
        founder_fit_verdict=winner.founder_fit.fit_verdict,
        target_buyer_count=winner.research.tam.estimated_target_users,
        annual_price_usd=winner.research.tam.annual_price_usd,
        bottom_up_tam_usd=winner.research.tam.bottom_up_tam_usd,
        customers_for_10k_mrr=winner.research.tam.customers_for_10k_mrr,
        startup_cost_usd=winner.research.estimated_startup_cost_usd,
    )
    stage2_res = run_stage2_pipeline(stage2_req)

    prd_md_path = OUTPUT_DIR / "google_doc_prd_top1.md"
    prd_md_path.write_text(stage2_res.google_doc_markdown, encoding="utf-8")
    print(
        f"  -> Generated full Google Doc PRD at: {prd_md_path} "
        f"(agent_mode={stage2_res.agent_mode})"
    )
    print("=" * 78)


if __name__ == "__main__":
    main()
