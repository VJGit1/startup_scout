"""
Stage 1 LangGraph Workflow:
Supervisor Agent orchestrates:
1. extract_ideas_node: Extracts candidate lifestyle startup ideas from Reddit posts
2. competitive_and_tam_research_node: Uses `competitive-market-researcher` SKILL.md + live web search
   to determine competitors, Bottom-Up TAM (Target Users x Annual Price), and Startup Cost
3. founder_market_fit_node: Uses `founder-market-fit` SKILL.md + `config/founder_profile.yaml`
4. startup_evaluator_node: Uses `startup-evaluator` SKILL.md rubric to score all ideas, pick the Top 3,
   and format rows for Google Sheets.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, TypedDict
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from src.models import (
    BottomUpTAM,
    CompetitorInfo,
    CompetitiveResearchSummary,
    EvaluatedStartupIdea,
    FounderMarketFitResult,
    LifestyleRubricScores,
    RedditPostInput,
    Stage1EvaluateRequest,
    Stage1EvaluateResponse,
)
from src.skill_loader import get_skill_prompt, load_founder_profile
from src.tools.search import (
    fetch_pain_points,
    get_sample_reddit_posts,
    invoke_structured_llm,
    live_web_search,
)

logger = logging.getLogger(__name__)

PAIN_PHRASES = (
    "manual",
    "wish",
    "tired",
    "paying too much",
    "hours",
    "spreadsheet",
    "nightmare",
    "no tool",
    "no app",
    "waste",
)


class CandidateIdeaDraft(BaseModel):
    idea_id: str
    idea_title: str
    one_line_pitch: str
    core_problem: str
    target_customer: str
    source_platform: str = "unknown"
    source_subreddit: str
    source_reddit_title: str
    source_reddit_url: str
    upvotes: int = 0


class CandidateIdeaList(BaseModel):
    ideas: List[CandidateIdeaDraft] = Field(default_factory=list)


class EvaluatorScoreOutput(BaseModel):
    scores: LifestyleRubricScores
    evaluator_verdict: str


class Stage1GraphState(TypedDict, total=False):
    posts: List[RedditPostInput]
    founder_profile: Dict[str, Any]
    supervisor_log: List[str]
    candidate_ideas: List[CandidateIdeaDraft]
    research_by_id: Dict[str, CompetitiveResearchSummary]
    founder_fit_by_id: Dict[str, FounderMarketFitResult]
    evaluated_ideas: List[EvaluatedStartupIdea]
    top_3_ideas: List[EvaluatedStartupIdea]
    source: str
    subreddits: List[str]
    fetch_live: bool
    source_used: str
    node_errors: List[str]
    fallback_used: bool


def _record_node_error(state: Stage1GraphState, node: str, exc: Exception) -> List[str]:
    message = f"{node}: {type(exc).__name__}: {exc}"
    logger.warning("%s", message)
    errors = list(state.get("node_errors") or [])
    errors.append(message)
    return errors


def _max_budget(founder_profile: Dict[str, Any]) -> float:
    raw = (
        founder_profile.get("founder", {})
        .get("constraints", {})
        .get("max_initial_startup_cost_usd", 2500)
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 2500.0


def _is_airline_text(text: str) -> bool:
    lowered = text.lower()
    return "airline" in lowered or "boeing" in lowered


def _clamp_score(value: float) -> float:
    return max(1.0, min(10.0, round(value, 1)))


def resolve_stage1_posts(
    posts: List[RedditPostInput] | None,
    source: str,
    subreddits: List[str] | None,
    fetch_live: bool,
) -> tuple[List[RedditPostInput], str, List[str]]:
    """Choose provided posts, a live source, or the curated fixture set."""
    errors: List[str] = []
    if posts:
        return list(posts), "provided", errors
    if not fetch_live:
        return get_sample_reddit_posts(), "curated", errors
    try:
        fetched = fetch_pain_points(source=source, subreddits=subreddits)
    except Exception as exc:
        message = f"fetch_pain_points: {type(exc).__name__}: {exc}"
        logger.warning("%s", message)
        errors.append(message)
        fetched = []
    if fetched:
        return fetched, source, errors
    message = f"fetch_pain_points returned zero items for source={source}"
    logger.warning("%s", message)
    errors.append(message)
    return [], source, errors


def _overlay_post_metadata(
    candidates: List[CandidateIdeaDraft],
    posts: List[RedditPostInput],
) -> List[CandidateIdeaDraft]:
    by_url = {post.url: post for post in posts if post.url}
    for candidate in candidates:
        post = by_url.get(candidate.source_reddit_url)
        if post is None:
            continue
        if candidate.source_platform in ("", "unknown"):
            candidate.source_platform = post.source_platform
        if not candidate.upvotes:
            candidate.upvotes = post.upvotes
    return candidates


def supervisor_init_node(state: Stage1GraphState) -> Dict[str, Any]:
    """Supervisor initializes Stage 1 and loads the Supervisor Orchestrator SKILL.md."""
    _ = get_skill_prompt("supervisor-orchestrator")
    posts = list(state.get("posts") or [])
    errors = list(state.get("node_errors") or [])
    source_used = state.get("source_used") or ""
    if not posts and not source_used:
        posts, source_used, fetch_errors = resolve_stage1_posts(
            [],
            state.get("source") or "hn",
            state.get("subreddits"),
            bool(state.get("fetch_live", True)),
        )
        errors.extend(fetch_errors)
    elif not source_used:
        source_used = "provided"
    founder_profile = state.get("founder_profile") or load_founder_profile()
    return {
        "posts": posts,
        "founder_profile": founder_profile,
        "source_used": source_used,
        "node_errors": errors,
        "supervisor_log": [
            f"Supervisor initialized Stage 1 with {len(posts)} posts from '{source_used}' and Founder Profile "
            f"'{founder_profile.get('founder', {}).get('name', 'Configured Founder')}'."
        ],
    }


def extract_ideas_node(state: Stage1GraphState) -> Dict[str, Any]:
    """Extract candidate startup ideas from Reddit posts."""
    posts = state["posts"]
    supervisor_skill = get_skill_prompt("supervisor-orchestrator")
    if not posts:
        logs = list(state.get("supervisor_log", []))
        logs.append("No source posts. Skipping idea extraction.")
        return {
            "candidate_ideas": [],
            "supervisor_log": logs,
            "node_errors": list(state.get("node_errors") or []),
            "fallback_used": bool(state.get("fallback_used")),
        }

    try:
        posts_text = "\n\n".join(
            f"[{i+1}] ({p.subreddit}) Title: {p.title}\nURL: {p.url}\nBody: {p.selftext}"
            for i, p in enumerate(posts)
        )
        res = invoke_structured_llm(
            system_prompt=supervisor_skill,
            user_prompt=(
                "Extract one concrete startup idea per post below so it can be evaluated by the "
                "Lifestyle Business Evaluator. Copy source_platform from the post when present.\n\n" + posts_text
            ),
            schema=CandidateIdeaList,
        )
        candidates = _overlay_post_metadata(res.ideas, posts)
        fallback_used = bool(state.get("fallback_used"))
        errors = list(state.get("node_errors") or [])
    except Exception as exc:
        errors = _record_node_error(state, "extract_ideas", exc)
        fallback_used = True
        candidates = _fallback_candidates(posts)

    logs = list(state.get("supervisor_log", []))
    logs.append(f"Extracted {len(candidates)} candidate ideas from source posts.")
    return {
        "candidate_ideas": candidates,
        "supervisor_log": logs,
        "node_errors": errors,
        "fallback_used": fallback_used,
    }


def competitive_and_tam_research_node(state: Stage1GraphState) -> Dict[str, Any]:
    """Run Competitive & Market Researcher Agent (`competitive-market-researcher` SKILL.md)."""
    researcher_skill = get_skill_prompt("competitive-market-researcher")
    research_by_id: Dict[str, CompetitiveResearchSummary] = {}

    errors = list(state.get("node_errors") or [])
    fallback_used = bool(state.get("fallback_used"))
    founder_profile = state.get("founder_profile") or {}

    for idea in state["candidate_ideas"]:
        search_snippets = live_web_search(f"{idea.idea_title} {idea.target_customer} software pricing competitors")
        if search_snippets.startswith("Web search fallback"):
            errors.append(f"competitive_and_tam_research: {search_snippets}")
        try:
            res = invoke_structured_llm(
                system_prompt=researcher_skill,
                user_prompt=(
                    f"Idea: {idea.idea_title}\nPitch: {idea.one_line_pitch}\n"
                    f"Problem: {idea.core_problem}\nTarget Customer: {idea.target_customer}\n\n"
                    f"Live Web Search Context:\n{search_snippets}\n\n"
                    "Provide structured CompetitiveResearchSummary including Bottom-Up TAM "
                    "(Target Users x Annual Price) and initial Startup Cost."
                ),
                schema=CompetitiveResearchSummary,
            )
            research_by_id[idea.idea_id] = res
        except Exception as exc:
            errors = _record_node_error({**state, "node_errors": errors}, "competitive_and_tam_research", exc)
            fallback_used = True
            research_by_id[idea.idea_id] = _fallback_research_for_idea(idea, founder_profile)

    logs = list(state.get("supervisor_log", []))
    logs.append(f"Completed Competitive & Bottom-Up TAM research for {len(research_by_id)} ideas.")
    return {
        "research_by_id": research_by_id,
        "supervisor_log": logs,
        "node_errors": errors,
        "fallback_used": fallback_used,
    }


def founder_market_fit_node(state: Stage1GraphState) -> Dict[str, Any]:
    """Run Founder-Market Fit Agent (`founder-market-fit` SKILL.md) using `config/founder_profile.yaml`."""
    fmf_skill = get_skill_prompt("founder-market-fit")
    founder_profile = state["founder_profile"]
    research_by_id = state["research_by_id"]
    founder_fit_by_id: Dict[str, FounderMarketFitResult] = {}
    errors = list(state.get("node_errors") or [])
    fallback_used = bool(state.get("fallback_used"))

    for idea in state["candidate_ideas"]:
        research = research_by_id[idea.idea_id]
        try:
            res = invoke_structured_llm(
                system_prompt=fmf_skill,
                user_prompt=(
                    f"Founder Profile YAML:\n{founder_profile}\n\n"
                    f"Candidate Startup Idea:\nTitle: {idea.idea_title}\n"
                    f"Problem: {idea.core_problem}\nTarget Customer: {idea.target_customer}\n"
                    f"Estimated Startup Cost: ${research.estimated_startup_cost_usd}\n"
                    "Assess Founder-Market Fit."
                ),
                schema=FounderMarketFitResult,
            )
            founder_fit_by_id[idea.idea_id] = res
        except Exception as exc:
            errors = _record_node_error({**state, "node_errors": errors}, "founder_market_fit", exc)
            fallback_used = True
            founder_fit_by_id[idea.idea_id] = _fallback_founder_fit(idea, research, founder_profile)

    logs = list(state.get("supervisor_log", []))
    logs.append(f"Completed Founder-Market Fit evaluation for {len(founder_fit_by_id)} ideas.")
    return {
        "founder_fit_by_id": founder_fit_by_id,
        "supervisor_log": logs,
        "node_errors": errors,
        "fallback_used": fallback_used,
    }


def startup_evaluator_node(state: Stage1GraphState) -> Dict[str, Any]:
    """
    Run Startup Evaluator Agent (`startup-evaluator` SKILL.md):
    Scores each candidate on the 5-part weighted Lifestyle Business Rubric,
    ranks them, and selects the Top 3.
    """
    evaluator_skill = get_skill_prompt("startup-evaluator")
    founder_profile = state["founder_profile"]
    max_budget = _max_budget(founder_profile)

    evaluated: List[EvaluatedStartupIdea] = []
    errors = list(state.get("node_errors") or [])
    fallback_used = bool(state.get("fallback_used"))

    for idea in state["candidate_ideas"]:
        research = state["research_by_id"][idea.idea_id]
        fmf = state["founder_fit_by_id"][idea.idea_id]
        try:
            eval_out = invoke_structured_llm(
                system_prompt=evaluator_skill,
                user_prompt=(
                    f"Idea: {idea.idea_title}\nProblem: {idea.core_problem}\n"
                    f"Founder budget ceiling: ${max_budget:,.0f}\n"
                    f"Research & TAM: {research.model_dump_json()}\n"
                    f"Founder-Market Fit: {fmf.model_dump_json()}\n"
                    "Score this idea using the weighted Lifestyle Business Rubric."
                ),
                schema=EvaluatorScoreOutput,
            )
            scores = eval_out.scores
            verdict = eval_out.evaluator_verdict
        except Exception as exc:
            errors = _record_node_error({**state, "node_errors": errors}, "startup_evaluator", exc)
            fallback_used = True
            scores, verdict = _fallback_evaluator_scores(idea, research, fmf, founder_profile)

        # Recalculate exact weighted formula to guarantee mathematical precision
        weighted = 10.0 * (
            0.25 * scores.pain_severity_score
            + 0.25 * scores.low_startup_cost_score
            + 0.20 * scores.competition_gap_score
            + 0.15 * scores.tam_sweet_spot_score
            + 0.15 * scores.founder_fit_score
        )
        scores.weighted_total_score = round(weighted, 1)

        evaluated.append(
            EvaluatedStartupIdea(
                idea_id=idea.idea_id,
                idea_title=idea.idea_title,
                one_line_pitch=idea.one_line_pitch,
                core_problem=idea.core_problem,
                target_customer=idea.target_customer,
                source_platform=idea.source_platform,
                source_subreddit=idea.source_subreddit,
                source_reddit_title=idea.source_reddit_title,
                source_reddit_url=idea.source_reddit_url,
                research=research,
                founder_fit=fmf,
                scores=scores,
                evaluator_verdict=verdict,
                rank=99,
                is_top_3=False,
                approval_status="Backlog",
            )
        )

    # Sort descending by weighted_total_score
    evaluated.sort(key=lambda x: x.scores.weighted_total_score, reverse=True)

    top_3: List[EvaluatedStartupIdea] = []
    for idx, item in enumerate(evaluated, 1):
        item.rank = idx
        qualifies_for_lifestyle = item.research.estimated_startup_cost_usd <= max_budget
        if len(top_3) < 3 and qualifies_for_lifestyle:
            item.is_top_3 = True
            item.approval_status = "Pending Review (Top 3)"
            top_3.append(item)
        else:
            item.is_top_3 = False
            item.approval_status = "Disqualified (Over Budget/Scope)" if not qualifies_for_lifestyle else "Backlog"

    logs = list(state.get("supervisor_log", []))
    logs.append(
        "Startup Evaluator Agent ranked all ideas and selected Top 3: "
        + ", ".join(f"#{i.rank} {i.idea_title} ({i.scores.weighted_total_score}/100)" for i in top_3)
    )
    return {
        "evaluated_ideas": evaluated,
        "top_3_ideas": top_3,
        "supervisor_log": logs,
        "node_errors": errors,
        "fallback_used": fallback_used,
    }


def build_stage1_graph():
    """Compile the Stage 1 LangGraph StateGraph."""
    workflow = StateGraph(Stage1GraphState)
    workflow.add_node("supervisor_init", supervisor_init_node)
    workflow.add_node("extract_ideas", extract_ideas_node)
    workflow.add_node("competitive_and_tam_research", competitive_and_tam_research_node)
    workflow.add_node("founder_market_fit", founder_market_fit_node)
    workflow.add_node("startup_evaluator", startup_evaluator_node)

    workflow.set_entry_point("supervisor_init")
    workflow.add_edge("supervisor_init", "extract_ideas")
    workflow.add_edge("extract_ideas", "competitive_and_tam_research")
    workflow.add_edge("competitive_and_tam_research", "founder_market_fit")
    workflow.add_edge("founder_market_fit", "startup_evaluator")
    workflow.add_edge("startup_evaluator", END)

    return workflow.compile()


def run_stage1_pipeline(request: Stage1EvaluateRequest) -> Stage1EvaluateResponse:
    """Execute the Stage 1 LangGraph pipeline and return structured output for n8n and Google Sheets."""
    fetch_live = bool(request.fetch_live or request.fetch_live_reddit)
    posts, source_used, fetch_errors = resolve_stage1_posts(
        request.posts,
        request.source,
        request.subreddits,
        fetch_live,
    )
    founder_profile = request.founder_profile_override or load_founder_profile()
    graph = build_stage1_graph()
    final_state = graph.invoke(
        {
            "posts": posts,
            "founder_profile": founder_profile,
            "source": request.source,
            "subreddits": request.subreddits,
            "fetch_live": fetch_live,
            "source_used": source_used,
            "node_errors": fetch_errors,
            "fallback_used": False,
        }
    )

    all_ideas: List[EvaluatedStartupIdea] = final_state["evaluated_ideas"]
    top_3: List[EvaluatedStartupIdea] = final_state["top_3_ideas"]
    sheet_rows = [idea.to_google_sheet_row() for idea in all_ideas]
    agent_mode = "fallback" if final_state.get("fallback_used") else "gemini"

    return Stage1EvaluateResponse(
        total_posts_analyzed=len(final_state.get("posts") or posts),
        top_3_ideas=top_3,
        all_evaluated_ideas=all_ideas,
        google_sheets_rows=sheet_rows,
        agent_mode=agent_mode,
        source_used=final_state.get("source_used") or source_used,
        node_errors=list(final_state.get("node_errors") or []),
    )


# ============================================================================
# Deterministic Domain Fallbacks (When running offline or without API Key)
# ============================================================================


def _post_fields(post: RedditPostInput) -> Dict[str, Any]:
    return {
        "source_platform": post.source_platform,
        "source_subreddit": post.subreddit,
        "source_reddit_title": post.title,
        "source_reddit_url": post.url,
        "upvotes": post.upvotes,
    }


def _fallback_candidates(posts: List[RedditPostInput]) -> List[CandidateIdeaDraft]:
    """Map known fixture posts to demo ideas and every other post to a software idea."""
    candidates: List[CandidateIdeaDraft] = []
    for idx, post in enumerate(posts, 1):
        lower = f"{post.title} {post.selftext}".lower()
        shared = _post_fields(post)
        if "coi" in lower or "insurance" in lower:
            candidates.append(
                CandidateIdeaDraft(
                    idea_id=f"idea-{idx}-certping",
                    idea_title="CertPing AI — Automated Subcontractor COI Compliance Tracker",
                    one_line_pitch="Zero-bloat PDF Certificate of Insurance parser and automated SMS/email expiry chaser for small contractors.",
                    core_problem="Small general contractors and property managers waste 5-6 hours/week chasing subcontractors for expiring Certificates of Insurance (COIs) because enterprise tools like Procore cost $600+/mo.",
                    target_customer="Independent general contractors, property managers, and construction SMBs (5-50 employees)",
                    **shared,
                )
            )
        elif "scope" in lower or "change order" in lower or "slack" in lower:
            candidates.append(
                CandidateIdeaDraft(
                    idea_id=f"idea-{idx}-scopeguard",
                    idea_title="ScopeGuard — 1-Click Slack/Email to Micro-Change-Order Bot",
                    one_line_pitch="Turn client 'quick asks' in Slack and email into polite, SOW-backed micro-change orders with 1-click Stripe approval.",
                    core_problem="Freelancers and boutique agencies lose 15-20% of project revenue to unbilled scope creep buried in Slack and email threads.",
                    target_customer="Boutique digital agencies, web dev shops, and B2B freelancers",
                    **shared,
                )
            )
        elif "stripe" in lower or "dunning" in lower or "failed-payment" in lower:
            candidates.append(
                CandidateIdeaDraft(
                    idea_id=f"idea-{idx}-pausesave",
                    idea_title="PauseSave — Indie Stripe Dunning + WhatsApp/SMS & 1-Click Pause Flow",
                    one_line_pitch="Plug-and-play failed-payment recovery and subscription pause widget built specifically for $2k-$30k MRR micro-SaaS.",
                    core_problem="Indie SaaS founders lose up to 30% of involuntary churn because default Stripe emails go to spam and enterprise retention tools cost $250-$1,000+/mo.",
                    target_customer="Bootstrapped micro-SaaS founders and subscription digital product creators",
                    **shared,
                )
            )
        elif "medspa" in lower or "clinic" in lower or "after 5pm" in lower:
            candidates.append(
                CandidateIdeaDraft(
                    idea_id=f"idea-{idx}-nightbook",
                    idea_title="NightBook AI — After-Hours IG/Google Maps DM Concierge for Clinics",
                    one_line_pitch="Menu-grounded after-hours DM responder and consult booker for local MedSpas and dental practices.",
                    core_problem="Local MedSpas and dental clinics spend $3k+/mo on ads but lose overnight IG/Google Maps inquiries because tools like Podium cost $500+/mo.",
                    target_customer="Independent MedSpas, cosmetic dental clinics, and boutique wellness studios",
                    **shared,
                )
            )
        elif _is_airline_text(lower):
            candidates.append(
                CandidateIdeaDraft(
                    idea_id=f"idea-{idx}-airline",
                    idea_title=post.title[:90] or "Nationwide airline",
                    one_line_pitch="Capital-intensive airline concept that cannot be a bootstrapped software lifestyle business.",
                    core_problem=post.selftext[:400] or post.title,
                    target_customer="Mass-market airline passengers",
                    **shared,
                )
            )
        else:
            problem = (post.selftext or post.title)[:400]
            candidates.append(
                CandidateIdeaDraft(
                    idea_id=f"idea-{idx}-software",
                    idea_title=f"Micro-SaaS: {post.title[:70]}",
                    one_line_pitch=f"A focused software tool for people dealing with: {post.title[:90]}",
                    core_problem=problem,
                    target_customer=f"People asking for a tool in {post.subreddit}",
                    **shared,
                )
            )
    return candidates


def _generic_startup_cost(max_budget: float) -> float:
    if max_budget <= 0:
        return 0.0
    return float(min(400.0, round(max_budget * 0.16, 2)))


def _generic_research(idea: CandidateIdeaDraft, max_budget: float) -> CompetitiveResearchSummary:
    monthly = 29.0
    annual = monthly * 12
    buyers = 20000
    cost = _generic_startup_cost(max_budget)
    customers_for_10k = int((10000 + monthly - 1) // monthly)
    return CompetitiveResearchSummary(
        competitors=[
            CompetitorInfo(
                name="Spreadsheets and manual workarounds",
                pricing="Free plus weekly labor",
                weakness_or_gap="The workaround still consumes the hours the buyer is trying to get back.",
            ),
            CompetitorInfo(
                name="Horizontal suites",
                pricing="$50-$300/mo",
                weakness_or_gap="Broader products bury this one workflow inside a suite the buyer does not want to migrate to.",
            ),
        ],
        competitive_wedge=(
            f"A single-purpose micro-SaaS for {idea.target_customer} aimed at: {idea.core_problem[:160]}"
        ),
        estimated_startup_cost_usd=cost,
        startup_cost_breakdown=(
            f"Domain, hosting, and model/API credits sized to stay under the founder's ${max_budget:,.0f} budget."
        ),
        tam=BottomUpTAM(
            target_buyer_segment=idea.target_customer,
            estimated_target_users=buyers,
            monthly_price_usd=monthly,
            annual_price_usd=annual,
            bottom_up_tam_usd=buyers * annual,
            customers_for_10k_mrr=customers_for_10k,
            tam_formula_explanation=(
                f"{buyers:,} reachable buyers x ${annual:,.0f}/yr (${monthly:.0f}/mo) = "
                f"${buyers * annual:,.0f}/yr bottom-up TAM. {customers_for_10k} customers reach $10k MRR."
            ),
        ),
    )


def _fallback_research_for_idea(
    idea: CandidateIdeaDraft,
    founder_profile: Dict[str, Any] | None = None,
) -> CompetitiveResearchSummary:
    cid = idea.idea_id.lower()
    if "certping" in cid:
        return CompetitiveResearchSummary(
            competitors=[
                CompetitorInfo(
                    name="Procore Compliance",
                    pricing="$600+/mo (Annual Enterprise Contract)",
                    weakness_or_gap="Massive ERP overkill for 5-50 person contractors who just need COI expiry tracking.",
                ),
                CompetitorInfo(
                    name="myCOI / Jones",
                    pricing="$350-$500+/mo",
                    weakness_or_gap="Long onboarding, enterprise sales calls, no self-serve $49/mo SMB tier.",
                ),
                CompetitorInfo(
                    name="Excel + Calendar Reminders",
                    pricing="Free (6 hrs/wk manual labor)",
                    weakness_or_gap="Subcontractors ignore manual emails; high liability risk when a lapsed policy is missed.",
                ),
            ],
            competitive_wedge="Self-serve $49/mo AI PDF parser + automated SMS/email vendor chaser with zero ERP migration.",
            estimated_startup_cost_usd=180.0,
            startup_cost_breakdown="$12/yr domain + $20/mo cloud hosting + $30/mo Gemini Vision PDF OCR API + $18/mo Twilio SMS + $100 initial outreach tooling.",
            tam=BottomUpTAM(
                target_buyer_segment="US/UK/CA small general contractors & property managers (5-50 employees)",
                estimated_target_users=140000,
                monthly_price_usd=49.0,
                annual_price_usd=588.0,
                bottom_up_tam_usd=82320000.0,
                customers_for_10k_mrr=205,
                tam_formula_explanation="140,000 small GCs/property managers × $588/yr ($49/mo) = $82.32M/yr Bottom-Up TAM (Only 205 customers needed for $10k MRR).",
            ),
        )
    if "scopeguard" in cid:
        return CompetitiveResearchSummary(
            competitors=[
                CompetitorInfo(
                    name="Bonsai / HoneyBook",
                    pricing="$39-$79/mo",
                    weakness_or_gap="Requires moving entire invoicing/CRM; doesn't detect scope creep inside Slack/email threads.",
                ),
                CompetitorInfo(
                    name="Scoro / Kantata",
                    pricing="$200-$500+/mo",
                    weakness_or_gap="Bloated agency PSA software hated by small 2-15 person studios.",
                ),
            ],
            competitive_wedge="Lightweight Slack bot & email forwarder that compares client requests to the SOW PDF and generates a 1-click $250+ Stripe change-order link.",
            estimated_startup_cost_usd=150.0,
            startup_cost_breakdown="$12/yr domain + $20/mo hosting + $25/mo Gemini API + $0 Stripe Connect + $93 launch assets.",
            tam=BottomUpTAM(
                target_buyer_segment="Boutique digital agencies, dev studios, and full-time B2B freelancers",
                estimated_target_users=180000,
                monthly_price_usd=39.0,
                annual_price_usd=468.0,
                bottom_up_tam_usd=84240000.0,
                customers_for_10k_mrr=257,
                tam_formula_explanation="180,000 boutique agencies/freelancers × $468/yr ($39/mo) = $84.24M/yr Bottom-Up TAM (257 customers needed for $10k MRR).",
            ),
        )
    if "pausesave" in cid:
        return CompetitiveResearchSummary(
            competitors=[
                CompetitorInfo(
                    name="Churnkey / ProfitWell Retain",
                    pricing="$250-$1,000+/mo",
                    weakness_or_gap="Priced for funded scale-ups; way too expensive for indie SaaS under $25k MRR.",
                ),
                CompetitorInfo(
                    name="Stripe Default Smart Retries",
                    pricing="Included in Stripe Billing (0.5%-0.8% of volume)",
                    weakness_or_gap="Generic plain-text emails land in spam; no SMS/WhatsApp nudge or 1-click pause modal.",
                ),
            ],
            competitive_wedge="Flat $29/mo indie-friendly Stripe webhook app with branded pause-instead-of-cancel modal and SMS card-update links.",
            estimated_startup_cost_usd=120.0,
            startup_cost_breakdown="$12 domain + $20/mo hosting + $38/mo SMS/email API credits + $50 Stripe test environment.",
            tam=BottomUpTAM(
                target_buyer_segment="Bootstrapped SaaS & subscription businesses ($2k-$30k MRR)",
                estimated_target_users=75000,
                monthly_price_usd=29.0,
                annual_price_usd=348.0,
                bottom_up_tam_usd=26100000.0,
                customers_for_10k_mrr=345,
                tam_formula_explanation="75,000 indie Stripe SaaS businesses × $348/yr ($29/mo) = $26.1M/yr Bottom-Up TAM (345 customers needed for $10k MRR).",
            ),
        )
    if "nightbook" in cid:
        return CompetitiveResearchSummary(
            competitors=[
                CompetitorInfo(
                    name="Podium / Weave",
                    pricing="$400-$650/mo (12-month lock-in)",
                    weakness_or_gap="Predatory annual contracts and high pricing frustrate single-location clinics.",
                ),
                CompetitorInfo(
                    name="Generic ManyChat Templates",
                    pricing="$15-$45/mo",
                    weakness_or_gap="Brittle decision trees that fail when patients ask specific treatment pricing or contraindictions.",
                ),
            ],
            competitive_wedge="No-contract $79/mo after-hours AI receptionist grounded strictly in the clinic's exact service menu PDF.",
            estimated_startup_cost_usd=250.0,
            startup_cost_breakdown="$12 domain + $30/mo hosting + $50/mo Meta/Google API + LLM tokens + $158 local clinic demo setup.",
            tam=BottomUpTAM(
                target_buyer_segment="Independent US/CA/UK MedSpas, cosmetic dentists, and aesthetic clinics",
                estimated_target_users=65000,
                monthly_price_usd=79.0,
                annual_price_usd=948.0,
                bottom_up_tam_usd=61620000.0,
                customers_for_10k_mrr=127,
                tam_formula_explanation="65,000 aesthetic/dental clinics × $948/yr ($79/mo) = $61.62M/yr Bottom-Up TAM (127 clinics needed for $10k MRR).",
            ),
        )
    if "airline" in cid or _is_airline_text(idea.idea_title):
        return CompetitiveResearchSummary(
            competitors=[
                CompetitorInfo(
                    name="Legacy Incumbents",
                    pricing="$10,000+/mo",
                    weakness_or_gap="Capital-intensive industry requiring millions in regulatory and hardware investment.",
                )
            ],
            competitive_wedge="None compatible with a bootstrapped lifestyle business.",
            estimated_startup_cost_usd=5000000.0,
            startup_cost_breakdown="Requires FAA certification, aircraft leasing, and millions in capital.",
            tam=BottomUpTAM(
                target_buyer_segment="Mass market airline passengers",
                estimated_target_users=1000000,
                monthly_price_usd=99.0,
                annual_price_usd=1188.0,
                bottom_up_tam_usd=1188000000.0,
                customers_for_10k_mrr=102,
                tam_formula_explanation="Capital-intensive physical operation; incompatible with bootstrapped software lifestyle model.",
            ),
        )
    return _generic_research(idea, _max_budget(founder_profile or {}))


def _fallback_founder_fit(
    idea: CandidateIdeaDraft,
    research: CompetitiveResearchSummary,
    founder_profile: Dict[str, Any],
) -> FounderMarketFitResult:
    cid = idea.idea_id.lower()
    max_budget = _max_budget(founder_profile)
    if research.estimated_startup_cost_usd > max_budget:
        return FounderMarketFitResult(
            founder_fit_score=1.5,
            fit_verdict="Poor Fit",
            strengths=["None — violates the configured lifestyle budget constraint."],
            blind_spots=["Requires capital or operating scope beyond this founder profile."],
            fit_rationale=(
                f"Disqualified: startup cost ${research.estimated_startup_cost_usd:,.0f} exceeds the "
                f"founder's ${max_budget:,.0f} max startup cost."
            ),
        )
    if "certping" in cid or "scopeguard" in cid:
        return FounderMarketFitResult(
            founder_fit_score=9.4,
            fit_verdict="Strong Fit",
            strengths=[
                "Directly leverages founder's Python, FastAPI, LLM document parsing, and n8n workflow automation stack.",
                "Buildable as a functional MVP in <14 days for under $200.",
                "High-margin B2B prosumer/SMB audience where saving 5 hrs/week or recovering 1 change order pays for a full year of subscription.",
            ],
            blind_spots=["Requires targeted outreach in contractor/agency communities to land first 15 design partners."],
            fit_rationale="Exceptional Founder-Market Fit (9.4/10): Combines AI document extraction + automated workflow triggers—the exact sweet spot of the founder profile.",
        )
    if "pausesave" in cid:
        return FounderMarketFitResult(
            founder_fit_score=8.8,
            fit_verdict="Strong Fit",
            strengths=[
                "Founders deeply understand indie SaaS tooling, APIs, and webhook automation.",
                "Near-zero support burden once Stripe webhooks are connected.",
            ],
            blind_spots=["Requires Stripe App Marketplace review and high trust around billing permissions."],
            fit_rationale="Strong Fit (8.8/10): Easy to build and market organically on r/SaaS and IndieHackers within a 20 hr/wk lifestyle schedule.",
        )
    if "nightbook" in cid:
        return FounderMarketFitResult(
            founder_fit_score=7.6,
            fit_verdict="Moderate Fit",
            strengths=["Strong technical fit for building the menu-grounded AI responder."],
            blind_spots=["Selling to local brick-and-mortar clinics requires more outbound calls/demos than pure self-serve SaaS."],
            fit_rationale="Moderate-to-Strong Fit (7.6/10): Technically straightforward, though local clinic GTM is slightly more sales-heavy.",
        )
    return FounderMarketFitResult(
        founder_fit_score=7.2,
        fit_verdict="Moderate Fit",
        strengths=[
            f"Startup cost stays within the ${max_budget:,.0f} founder budget.",
            "The workflow can be prototyped as a narrow software MVP.",
        ],
        blind_spots=["Buyer willingness to pay still needs a direct conversation with people who wrote the source post."],
        fit_rationale=(
            f"Moderate Fit (7.2/10): {idea.idea_title} is a software workflow inside the founder budget, "
            "with distribution still unproven."
        ),
    )


def _heuristic_scores(
    idea: CandidateIdeaDraft,
    research: CompetitiveResearchSummary,
    fmf: FounderMarketFitResult,
    max_budget: float,
) -> tuple[LifestyleRubricScores, str]:
    text = f"{idea.idea_title} {idea.one_line_pitch} {idea.core_problem}".lower()
    hits = sum(1 for phrase in PAIN_PHRASES if phrase in text)
    pain = 4.0 + hits
    if len(idea.core_problem) > 180:
        pain += 1.0
    elif len(idea.core_problem) > 80:
        pain += 0.5
    if idea.upvotes >= 100:
        pain += 1.0
    elif idea.upvotes >= 20:
        pain += 0.5
    cost_score = 8.5 if research.estimated_startup_cost_usd <= max_budget else 1.5
    scores = LifestyleRubricScores(
        pain_severity_score=_clamp_score(pain),
        low_startup_cost_score=_clamp_score(cost_score),
        competition_gap_score=6.0,
        tam_sweet_spot_score=6.0,
        founder_fit_score=fmf.founder_fit_score,
        weighted_total_score=0.0,
    )
    verdict = (
        f"Heuristic score for {idea.idea_title}: pain phrases={hits}, "
        f"startup cost ${research.estimated_startup_cost_usd:,.0f} vs ${max_budget:,.0f} budget, "
        f"upvotes={idea.upvotes}."
    )
    return scores, verdict


def _fallback_evaluator_scores(
    idea: CandidateIdeaDraft,
    research: CompetitiveResearchSummary,
    fmf: FounderMarketFitResult,
    founder_profile: Dict[str, Any] | None = None,
) -> tuple[LifestyleRubricScores, str]:
    cid = idea.idea_id.lower()
    max_budget = _max_budget(founder_profile or {})
    if "certping" in cid:
        return (
            LifestyleRubricScores(
                pain_severity_score=9.5,
                low_startup_cost_score=9.4,
                competition_gap_score=9.2,
                tam_sweet_spot_score=9.0,
                founder_fit_score=fmf.founder_fit_score,
                weighted_total_score=92.8,
            ),
            "Rank #1 Winner: High-urgency B2B compliance pain (6 hrs/wk wasted + legal liability risk), massive price gap under $500/mo incumbents, $180 startup cost, and $82M niche TAM.",
        )
    if "scopeguard" in cid:
        return (
            LifestyleRubricScores(
                pain_severity_score=9.2,
                low_startup_cost_score=9.5,
                competition_gap_score=8.8,
                tam_sweet_spot_score=8.9,
                founder_fit_score=fmf.founder_fit_score,
                weighted_total_score=91.8,
            ),
            "Rank #2 Winner: Directly generates revenue for users on Day 1 (1 recovered change order = 10x monthly fee), $150 startup cost, and strong viral distribution among agencies.",
        )
    if "pausesave" in cid:
        return (
            LifestyleRubricScores(
                pain_severity_score=8.6,
                low_startup_cost_score=9.5,
                competition_gap_score=8.2,
                tam_sweet_spot_score=8.4,
                founder_fit_score=fmf.founder_fit_score,
                weighted_total_score=87.5,
            ),
            "Rank #3 Winner: Ultra-lean micro-SaaS ($120 startup cost) with clear ROI for indie founders priced out of $250+/mo retention tools.",
        )
    if "nightbook" in cid:
        return (
            LifestyleRubricScores(
                pain_severity_score=8.5,
                low_startup_cost_score=8.6,
                competition_gap_score=7.8,
                tam_sweet_spot_score=8.5,
                founder_fit_score=fmf.founder_fit_score,
                weighted_total_score=82.5,
            ),
            "Rank #4 Runner-Up: Great unit economics ($79/mo) and clear pain, but slightly below Top 3 due to local clinic sales friction and Meta API approval steps.",
        )
    if "airline" in cid or research.estimated_startup_cost_usd > max_budget:
        return (
            LifestyleRubricScores(
                pain_severity_score=3.0,
                low_startup_cost_score=1.0,
                competition_gap_score=2.0,
                tam_sweet_spot_score=4.0,
                founder_fit_score=fmf.founder_fit_score,
                weighted_total_score=0.0,
            ),
            "Disqualified: Violates lifestyle business budget and asset-light constraints.",
        )
    return _heuristic_scores(idea, research, fmf, max_budget)
