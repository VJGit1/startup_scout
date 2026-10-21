"""
Stage 2 LangGraph Workflow (Triggered when a row in Google Sheets is marked 'Approved'):
Supervisor Agent orchestrates:
1. deep_research_node (`competitive-market-researcher` SKILL.md + live web search)
2. pm_strategist_node (`pm-strategist` SKILL.md -> Problem Statement, Value Prop, <30-Day MVP, GTM,
   and Kano Model Feature Prioritization mapped to Reddit pain points)
3. risk_analyst_node (`risk-analyst` SKILL.md -> 5-Category Risk Matrix + Open Questions & 48h Validation)
4. compile_prd_node (Formats the complete Google Doc PRD using `references/prd_template.md`)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, TypedDict
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from src.models import (
    KanoFeatureItem,
    OpenQuestionItem,
    PRDContentSections,
    RiskItem,
    Stage2PRDRequest,
    Stage2PRDResponse,
)
from src.skill_loader import SKILLS_DIR, get_skill_prompt, load_founder_profile
from src.tools.search import invoke_structured_llm, live_web_search

logger = logging.getLogger(__name__)
PRD_TEMPLATE_PATH = SKILLS_DIR / "pm-strategist" / "references" / "prd_template.md"


class DeepResearchOutput(BaseModel):
    competition_and_tam_analysis: str


class PMStrategistOutput(BaseModel):
    problem_statement: str
    value_proposition: str
    mvp_scope_and_architecture: str
    kano_features: List[KanoFeatureItem] = Field(default_factory=list)
    gtm_and_pricing_strategy: str


class RiskAnalystOutput(BaseModel):
    risks: List[RiskItem] = Field(default_factory=list)
    open_questions: List[OpenQuestionItem] = Field(default_factory=list)


class Stage2GraphState(TypedDict, total=False):
    request: Stage2PRDRequest
    founder_profile: Dict[str, Any]
    web_research_context: str
    competition_and_tam_analysis: str
    pm_output: PMStrategistOutput
    risk_output: RiskAnalystOutput
    sections: PRDContentSections
    google_doc_markdown: str
    node_errors: List[str]
    fallback_used: bool


def _record_node_error(state: Stage2GraphState, node: str, exc: Exception) -> List[str]:
    message = f"{node}: {type(exc).__name__}: {exc}"
    logger.warning("%s", message)
    errors = list(state.get("node_errors") or [])
    errors.append(message)
    return errors


def _founder_prompt(state: Stage2GraphState) -> str:
    profile = state.get("founder_profile") or {}
    name = profile.get("founder", {}).get("name", "Configured Founder")
    return f"Founder profile name: {name}\nProfile:\n{profile}\n"


def _is_certping(req: Stage2PRDRequest) -> bool:
    blob = f"{req.idea_id or ''} {req.idea_title}".lower()
    return "certping" in blob


def deep_research_node(state: Stage2GraphState) -> Dict[str, Any]:
    """Deep-dive market & competitor analysis for the approved idea."""
    req = state["request"]
    researcher_skill = get_skill_prompt("competitive-market-researcher")
    web_ctx = live_web_search(f"{req.idea_title} {req.target_customer} competitors pricing alternatives")
    errors = list(state.get("node_errors") or [])
    fallback_used = bool(state.get("fallback_used"))
    if web_ctx.startswith("Web search fallback"):
        errors.append(f"deep_research: {web_ctx}")

    try:
        out = invoke_structured_llm(
            system_prompt=researcher_skill,
            user_prompt=(
                f"{_founder_prompt(state)}\n"
                f"Approved Startup Idea: {req.idea_title}\n"
                f"Pitch: {req.one_line_pitch}\n"
                f"Problem: {req.core_problem}\n"
                f"Target Customer: {req.target_customer}\n"
                f"Stage 1 TAM Summary: {req.bottom_up_tam_summary}\n"
                f"Stage 1 Startup Cost: {req.startup_cost_summary}\n"
                f"Stage 1 Competitors: {req.competitors_summary}\n"
                f"Live Web Search Context:\n{web_ctx}\n\n"
                "Write a comprehensive markdown section covering Direct/Indirect Competitors, "
                "our Lifestyle Business Wedge, Bottom-Up TAM/SAM/SOM breakdown, and Month 1-3 Startup Cost table. "
                "Describe this approved idea, not a different product."
            ),
            schema=DeepResearchOutput,
        )
        comp_md = out.competition_and_tam_analysis
    except Exception as exc:
        errors = _record_node_error({**state, "node_errors": errors}, "deep_research", exc)
        fallback_used = True
        comp_md = _fallback_deep_research(req)

    return {
        "web_research_context": web_ctx,
        "competition_and_tam_analysis": comp_md,
        "node_errors": errors,
        "fallback_used": fallback_used,
    }


def pm_strategist_node(state: Stage2GraphState) -> Dict[str, Any]:
    """
    PM Strategist Agent (`pm-strategist` SKILL.md):
    Authors Problem Statement, Value Prop, <30-day MVP Scope, GTM, and Kano Model Feature Prioritization.
    """
    req = state["request"]
    pm_skill = get_skill_prompt("pm-strategist", include_references=False)
    errors = list(state.get("node_errors") or [])
    fallback_used = bool(state.get("fallback_used"))

    try:
        pm_out = invoke_structured_llm(
            system_prompt=pm_skill,
            user_prompt=(
                f"{_founder_prompt(state)}\n"
                f"Approved Idea: {req.idea_title}\n"
                f"One-Line Pitch: {req.one_line_pitch}\n"
                f"Source pain point ({req.source_subreddit}): {req.core_problem}\n"
                f"Source title: {req.source_reddit_title} ({req.source_reddit_url})\n"
                f"Target Customer: {req.target_customer}\n"
                f"Competitive & TAM Research:\n{state['competition_and_tam_analysis']}\n\n"
                "Generate the PM deliverables including Kano Model Feature Prioritization "
                "(Basic Expectation, Performance Feature, Delighter) mapped directly to this idea's pain points."
            ),
            schema=PMStrategistOutput,
        )
    except Exception as exc:
        errors = _record_node_error({**state, "node_errors": errors}, "pm_strategist", exc)
        fallback_used = True
        pm_out = _fallback_pm_output(req)

    return {"pm_output": pm_out, "node_errors": errors, "fallback_used": fallback_used}


def risk_analyst_node(state: Stage2GraphState) -> Dict[str, Any]:
    """
    Risk Analysis Agent (`risk-analyst` SKILL.md):
    Generates the 5-Category Lifestyle Risk Matrix + Open Questions & 48-Hour Validation Plan.
    """
    req = state["request"]
    risk_skill = get_skill_prompt("risk-analyst")
    pm_out = state["pm_output"]
    errors = list(state.get("node_errors") or [])
    fallback_used = bool(state.get("fallback_used"))

    try:
        risk_out = invoke_structured_llm(
            system_prompt=risk_skill,
            user_prompt=(
                f"{_founder_prompt(state)}\n"
                f"Idea: {req.idea_title}\n"
                f"Problem Statement: {pm_out.problem_statement}\n"
                f"MVP Scope: {pm_out.mvp_scope_and_architecture}\n"
                f"GTM Strategy: {pm_out.gtm_and_pricing_strategy}\n\n"
                "Identify 5-6 concrete risks (Market, Distribution, Platform/API, Competition, Lifestyle Support Burden) "
                "and 4-5 Open Questions with <48-hour validation tests for this specific idea."
            ),
            schema=RiskAnalystOutput,
        )
    except Exception as exc:
        errors = _record_node_error({**state, "node_errors": errors}, "risk_analyst", exc)
        fallback_used = True
        risk_out = _fallback_risk_output(req)

    return {"risk_output": risk_out, "node_errors": errors, "fallback_used": fallback_used}


def compile_prd_node(state: Stage2GraphState) -> Dict[str, Any]:
    """Supervisor compiles all specialist outputs into the final Google Doc PRD markdown."""
    req = state["request"]
    pm_out = state["pm_output"]
    risk_out = state["risk_output"]
    comp_analysis = state["competition_and_tam_analysis"]

    sections = PRDContentSections(
        problem_statement=pm_out.problem_statement,
        competition_and_tam_analysis=comp_analysis,
        value_proposition=pm_out.value_proposition,
        mvp_scope_and_architecture=pm_out.mvp_scope_and_architecture,
        kano_features=pm_out.kano_features,
        gtm_and_pricing_strategy=pm_out.gtm_and_pricing_strategy,
        risks=risk_out.risks,
        open_questions=risk_out.open_questions,
    )

    kano_rows = [
        "| Feature | Kano Category | Mapped Reddit Pain Point | User Impact | Build Effort (Days) | Phase |",
        "| :--- | :--- | :--- | :--- | :---: | :--- |",
    ]
    for f in sections.kano_features:
        kano_rows.append(
            f"| **{f.feature_name}** | `{f.kano_category}` | {f.mapped_reddit_pain_point} | "
            f"{f.user_impact} | {f.build_effort_days}d | {f.mvp_phase} |"
        )
    kano_table_md = "\n".join(kano_rows)

    risk_rows = [
        "| Category | Risk Description | Severity | Likelihood | Mitigation Strategy |",
        "| :--- | :--- | :---: | :---: | :--- |",
    ]
    for r in sections.risks:
        risk_rows.append(
            f"| **{r.category}** | {r.risk_description} | {r.severity} | {r.likelihood} | {r.mitigation_strategy} |"
        )
    risk_table_md = "\n".join(risk_rows)

    open_q_lines = []
    for idx, q in enumerate(sections.open_questions, 1):
        open_q_lines.append(
            f"### Q{idx}: {q.question}\n"
            f"- **Why It Matters:** {q.why_it_matters}\n"
            f"- **48-Hour Validation Experiment:** {q.validation_test_48h}\n"
        )
    open_q_md = "\n".join(open_q_lines)

    doc_md = _render_prd_template(
        req=req,
        founder_profile=state.get("founder_profile") or {},
        sections=sections,
        kano_table_md=kano_table_md,
        risk_table_md=risk_table_md,
        open_q_md=open_q_md,
    )
    return {"sections": sections, "google_doc_markdown": doc_md}


def _shown(value: Any) -> str:
    """Render a Stage 2 header value. Blank numbers stay n/a."""
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value.strip() or "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _money(value: Any) -> str:
    """Format a numeric amount. A sheet string such as '$200' is kept as written."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "n/a"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not value.is_integer():
            return f"${value:,.2f}"
        return f"${int(value):,}"
    return str(value)


def _render_prd_template(
    req: Stage2PRDRequest,
    founder_profile: Dict[str, Any],
    sections: PRDContentSections,
    kano_table_md: str,
    risk_table_md: str,
    open_q_md: str,
) -> str:
    """Fill the bundled PRD template. Numeric fields absent from the request use its summary strings."""
    template = PRD_TEMPLATE_PATH.read_text(encoding="utf-8")
    founder_name = founder_profile.get("founder", {}).get("name", "Configured Founder")
    source_label = req.source_reddit_title or req.source_subreddit or "source post"
    if req.source_reddit_url:
        source_threads = f"[{source_label}]({req.source_reddit_url}) ({req.source_subreddit})"
    else:
        source_threads = f"{source_label} ({req.source_subreddit})"
    cost_summary = req.startup_cost_summary or "n/a"
    fit_summary = req.founder_fit_summary or "n/a"
    replacements = {
        "idea_title": req.idea_title,
        "one_line_pitch": req.one_line_pitch or req.idea_title,
        "source_threads": source_threads,
        "target_customer": req.target_customer,
        "total_score": _shown(req.total_score),
        "founder_fit_score": _shown(req.founder_fit_score),
        "problem_statement": sections.problem_statement,
        "reddit_pain_evidence": req.core_problem,
        "target_buyer_count": _shown(req.target_buyer_count),
        "annual_price_point": _money(req.annual_price_usd),
        "bottom_up_tam_usd": _money(req.bottom_up_tam_usd),
        "ten_k_mrr_customers": _shown(req.customers_for_10k_mrr),
        "competitive_analysis": sections.competition_and_tam_analysis,
        "startup_cost_usd": _money(req.startup_cost_usd),
        "startup_cost_breakdown": cost_summary,
        "founder_fit_verdict": (req.founder_fit_verdict or "").strip() or "n/a",
        "founder_fit_rationale": fit_summary,
        "value_proposition": sections.value_proposition,
        "mvp_scope": sections.mvp_scope_and_architecture,
        "kano_prioritization_table": kano_table_md,
        "gtm_strategy": sections.gtm_and_pricing_strategy,
        "risk_matrix": risk_table_md,
        "open_questions": open_q_md,
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    scope_line = "**Business Scope:** Bootstrapped Lifestyle Business (<30-Day MVP, Low Cost, High Margin)"
    if scope_line in rendered:
        rendered = rendered.replace(scope_line, scope_line + f"\n- **Founder Profile:** {founder_name}", 1)
    return rendered


def build_stage2_graph():
    """Compile the Stage 2 LangGraph StateGraph."""
    workflow = StateGraph(Stage2GraphState)
    workflow.add_node("deep_research", deep_research_node)
    workflow.add_node("pm_strategist", pm_strategist_node)
    workflow.add_node("risk_analyst", risk_analyst_node)
    workflow.add_node("compile_prd", compile_prd_node)

    workflow.set_entry_point("deep_research")
    workflow.add_edge("deep_research", "pm_strategist")
    workflow.add_edge("pm_strategist", "risk_analyst")
    workflow.add_edge("risk_analyst", "compile_prd")
    workflow.add_edge("compile_prd", END)

    return workflow.compile()


def run_stage2_pipeline(request: Stage2PRDRequest) -> Stage2PRDResponse:
    """Execute the Stage 2 LangGraph pipeline to generate the complete Google Doc PRD."""
    founder_profile = request.founder_profile_override or load_founder_profile()
    graph = build_stage2_graph()
    final_state = graph.invoke(
        {
            "request": request,
            "founder_profile": founder_profile,
            "node_errors": [],
            "fallback_used": False,
        }
    )

    return Stage2PRDResponse(
        idea_id=request.idea_id or "approved-idea-1",
        document_title=f"PRD - {request.idea_title}",
        sections=final_state["sections"],
        google_doc_markdown=final_state["google_doc_markdown"],
        agent_mode="fallback" if final_state.get("fallback_used") else "gemini",
        source_used="approved_idea",
        node_errors=list(final_state.get("node_errors") or []),
    )


# ============================================================================
# Deterministic Domain Fallbacks for Stage 2 PRD Generation
# ============================================================================


def _generic_deep_research(req: Stage2PRDRequest) -> str:
    wedge = req.competitive_wedge or f"A narrow tool for {req.target_customer}"
    competitors = req.competitors_summary or "Spreadsheets and manual workarounds"
    tam = req.bottom_up_tam_summary or "Bottom-up TAM is not quantified yet."
    cost = req.startup_cost_summary or "Startup cost stays inside the founder budget."
    return (
        f"### Competitive Landscape\n"
        f"| Option | Notes |\n"
        f"| :--- | :--- |\n"
        f"| {competitors} | Current alternatives considered by {req.target_customer} |\n"
        f"| **{req.idea_title}** | {wedge} |\n\n"
        f"### Bottom-Up TAM\n{tam}\n\n"
        f"### Startup Cost\n{cost}\n\n"
        f"Problem being sized: {req.core_problem}\n"
    )


def _fallback_deep_research(req: Stage2PRDRequest) -> str:
    if not _is_certping(req):
        return _generic_deep_research(req)
    return f"""### Competitive Landscape
| Competitor / Workaround | Pricing | Core Weakness Highlighted on Reddit |
| :--- | :--- | :--- |
| **Enterprise Suites (e.g., Procore / myCOI / Scoro)** | `$350 – $600+/mo` (Annual lock-in) | Built for 200+ employee enterprises; requires full ERP migration and sales calls. |
| **Generic Horizontal Tools (Spreadsheets / Calendars)** | `$0` (`5–6 hrs/week` manual admin) | Zero automated PDF parsing or proactive vendor SMS/email follow-up; high human error. |
| **{req.idea_title} (Our Wedge)** | **`$49/mo` Self-Serve** | **Single-purpose 5-minute setup that solves the exact Reddit bottleneck automatically.** |

### Bottom-Up TAM / SAM / SOM
- ** Formula:** $\\text{{Bottom-Up TAM}} = N_{{\\text{{target\\_buyers}}}} \\times P_{{\\text{{annual}}}}$
- **Target Buyer Pool ($N$):** `140,000` reachable SMBs / prosumers in US, Canada, and UK experiencing `{req.core_problem[:90]}...`
- **Annual Price ($P$):** `$49/mo × 12 = $588/year`
- **Bottom-Up TAM:** **`$82,320,000 / year`** ({req.bottom_up_tam_summary or '140,000 buyers × $588/yr'})
- **Lifestyle SOM Goal (`$10,000 MRR`):** Only **`205 paying customers`** (`0.14%` of niche market share), maintainable by 1–2 founders in `<15 hrs/week`.

### Initial Startup Cost Breakdown (`<$200` Total to Launch)
- **Domain & DNS:** `$12/yr`
- **Cloud Hosting & Database (Render/Supabase/Vercel):** `$20/mo`
- **AI / LLM Extraction API (Gemini 2.5 Flash):** `~$30/mo` (approx. `$0.002` per document/workflow run)
- **Transactional Email & SMS (Resend + Twilio):** `~$18/mo`
- **Initial Organic GTM Tooling:** `$100` one-time"""


def _generic_pm_output(req: Stage2PRDRequest) -> PMStrategistOutput:
    pain = req.core_problem or req.idea_title
    pitch = req.one_line_pitch or req.idea_title
    wedge = req.competitive_wedge or f"a narrower workflow than the current workaround for {req.target_customer}"
    source_label = req.source_reddit_title or req.source_subreddit or "the source post"
    return PMStrategistOutput(
        problem_statement=f"**Pain:** {pain}\n\n**Who feels it:** {req.target_customer}",
        value_proposition=(
            f"For {req.target_customer}, **{req.idea_title}** is {pitch}. "
            f"The wedge is {wedge}."
        ),
        mvp_scope_and_architecture=(
            f"### 30-day MVP for {req.idea_title}\n"
            f"1. Capture the workflow described by: {pain[:240]}\n"
            "2. Show one automated result the buyer can check without a sales call.\n"
            "3. Charge a self-serve monthly price and skip enterprise onboarding.\n\n"
            "Non-goals: no hardware build, no two-sided marketplace, and no custom mobile app."
        ),
        kano_features=[
            KanoFeatureItem(
                feature_name=f"Core workflow for {req.idea_title}",
                kano_category="Basic Expectation",
                mapped_reddit_pain_point=pain[:180],
                user_impact="Removes the manual step described in the source post.",
                build_effort_days=5,
                mvp_phase="Day-1 MVP (<30 Days)",
            ),
            KanoFeatureItem(
                feature_name="Self-serve setup",
                kano_category="Performance Feature",
                mapped_reddit_pain_point=source_label[:180],
                user_impact=f"Lets {req.target_customer} reach a result without a demo call.",
                build_effort_days=3,
                mvp_phase="Day-1 MVP (<30 Days)",
            ),
            KanoFeatureItem(
                feature_name="Weekly status digest",
                kano_category="Delighter",
                mapped_reddit_pain_point=pain[:180],
                user_impact="A short weekly summary replaces checking the workflow by hand.",
                build_effort_days=2,
                mvp_phase="v1.1 Fast Follow",
            ),
        ],
        gtm_and_pricing_strategy=(
            f"Price {req.idea_title} as a low-touch monthly subscription for {req.target_customer}. "
            f"Start with people who already described this pain in {source_label}. "
            f"TAM context: {req.bottom_up_tam_summary or 'not yet quantified'}."
        ),
    )


def _fallback_pm_output(req: Stage2PRDRequest) -> PMStrategistOutput:
    if not _is_certping(req):
        return _generic_pm_output(req)
    return PMStrategistOutput(
        problem_statement=(
            f"**User Pain Originating from {req.source_subreddit}:**\n"
            f"{req.core_problem}\n\n"
            "**Why Current Solutions Fail:**\n"
            "Target buyers are trapped between two bad options: spending 5–6 hours every week doing manual "
            "copy-pasting and follow-ups in spreadsheets, or paying `$400–$600+/month` on bloated enterprise "
            "platforms that take weeks to onboard. They want a focused, single-purpose tool that works out of "
            "the box in 5 minutes."
        ),
        value_proposition=(
            f"**Positioning Statement:**\n"
            f"> *For **{req.target_customer}** who waste hours every week on **{req.core_problem[:80]}...**, "
            f"**{req.idea_title}** is a self-serve workflow automation micro-SaaS that eliminates 90% of manual "
            f"chasing in under 5 minutes—unlike `$500+/mo` enterprise suites or error-prone spreadsheets.*\n\n"
            "- **Primary Value Metric:** Hours saved per week (`5+ hrs/wk`) + costly compliance/revenue leaks prevented.\n"
            "- **Time-to-Value:** Under 3 minutes from signup to first automated workflow run."
        ),
        mvp_scope_and_architecture=(
            "### Core 4-Step User Journey\n"
            "1. **Drop & Parse:** User uploads or forwards existing PDFs/emails (zero manual data entry).\n"
            "2. **AI Extraction & Validation:** Gemini structured output extracts key dates, dollar amounts, coverage/scope rules, and flags gaps.\n"
            "3. **Automated Nudge Engine:** Scheduled cron sends polite email/SMS reminders with a magic upload/approval link (no login required for external vendors/clients).\n"
            "4. **Weekly Peace-of-Mind Digest:** Every Monday at 8am, the owner gets a 30-second green/yellow/red status digest.\n\n"
            "### Explicit Non-Goals for Day-1 MVP (Preventing Scope Creep)\n"
            "- No full ERP, accounting, or payroll replacement.\n"
            "- No custom native mobile apps (magic mobile web links only).\n"
            "- No complex multi-department RBAC permissions in v1."
        ),
        kano_features=[
            KanoFeatureItem(
                feature_name="AI Document / Thread Parser (Zero Manual Entry)",
                kano_category="Basic Expectation",
                mapped_reddit_pain_point="Users hate manually typing dates/clauses from PDFs and threads into spreadsheets.",
                user_impact="Eliminates 100% of manual data entry on Day 1.",
                build_effort_days=4,
                mvp_phase="Day-1 MVP (<30 Days)",
            ),
            KanoFeatureItem(
                feature_name="No-Login Vendor/Client Magic Upload & Approval Link",
                kano_category="Basic Expectation",
                mapped_reddit_pain_point="External subcontractors/clients refuse to create accounts on enterprise portals.",
                user_impact="3x higher completion rate from external recipients.",
                build_effort_days=4,
                mvp_phase="Day-1 MVP (<30 Days)",
            ),
            KanoFeatureItem(
                feature_name="Automated Multi-Channel Follow-Up Cadence (Email + SMS)",
                kano_category="Performance Feature",
                mapped_reddit_pain_point="Spending 6 hours every Friday manually chasing people who ignore emails.",
                user_impact="Saves 5+ hours/week; SMS nudges get 85% open rate within 15 minutes.",
                build_effort_days=5,
                mvp_phase="Day-1 MVP (<30 Days)",
            ),
            KanoFeatureItem(
                feature_name="1-Click Instant Gap Rejection & Auto-Reply",
                kano_category="Delighter",
                mapped_reddit_pain_point="Receiving an expired or insufficient document and having to write a rejection email manually.",
                user_impact="Instant 'wow' moment—AI spots the exact missing requirement and asks the sender to fix it automatically.",
                build_effort_days=3,
                mvp_phase="Day-1 MVP (<30 Days)",
            ),
            KanoFeatureItem(
                feature_name="QuickBooks / Slack / Webhook 2-Way Sync",
                kano_category="Performance Feature",
                mapped_reddit_pain_point="Keeping existing bookkeeping or team chat updated once an item is approved.",
                user_impact="Reduces context switching for growing teams.",
                build_effort_days=6,
                mvp_phase="v1.1 Fast Follow",
            ),
        ],
        gtm_and_pricing_strategy=(
            "### Bootstrapped Pricing Tiers\n"
            "- **Starter (`$29/mo`):** Up to 25 active tracked items/vendors, email reminders, AI extraction.\n"
            "- **Pro (`$49/mo` - Core Tier):** Up to 100 active items, SMS + Email cadences, custom branding, instant gap check.\n"
            "- **Growth (`$99/mo`):** Unlimited items, multi-user alerts, webhook integrations.\n\n"
            "### First 50 Paying Customers Playbook\n"
            "1. **Direct Reddit Thread Re-Engagement (Customers 1–10):** Reply to and DM the original posters and commenters in `r/smallbusiness`, `r/freelance`, and `r/SaaS` offering a free 30-day founding member setup.\n"
            "2. **Free Micro-Tool Lead Magnet (Customers 11–25):** Launch a free 'Instant PDF Compliance / Scope Checker' page where users drop 1 file to see instant AI analysis, then upsell automated monitoring for `$49/mo`.\n"
            "3. **Comparison SEO & Niche Forums (Customers 26–50):** Publish high-intent 'Lightweight Procore/myCOI Alternative for Small Contractors' landing pages."
        ),
    )


def _generic_risk_output(req: Stage2PRDRequest) -> RiskAnalystOutput:
    return RiskAnalystOutput(
        risks=[
            RiskItem(
                category="Market & Willingness-to-Pay Risk",
                risk_description=f"{req.target_customer} may describe the pain behind {req.idea_title} and still refuse another subscription.",
                severity="High",
                likelihood="Medium",
                mitigation_strategy="Price against the hours or revenue the source post says are already being lost, and offer a short self-serve trial.",
            ),
            RiskItem(
                category="Distribution & Cold-Start Risk",
                risk_description=f"The first buyers for {req.idea_title} may be hard to reach after the original {req.source_subreddit} thread goes quiet.",
                severity="Medium",
                likelihood="High",
                mitigation_strategy="Reply helpfully where the pain was posted, then pair that with a one-page offer and direct messages.",
            ),
            RiskItem(
                category="Competition Risk",
                risk_description=req.competitive_wedge or f"A broader incumbent could copy the narrow workflow in {req.idea_title}.",
                severity="Medium",
                likelihood="Medium",
                mitigation_strategy="Ship the smallest workflow that the source post asked for and stay narrower than the suite products.",
            ),
            RiskItem(
                category="Lifestyle & Support Burden Risk",
                risk_description=f"Hands-on onboarding for {req.target_customer} could exceed a part-time founder schedule.",
                severity="Medium",
                likelihood="Low",
                mitigation_strategy="Make the first run self-serve: paste the source workflow, get a result, and pay without a demo call.",
            ),
        ],
        open_questions=[
            OpenQuestionItem(
                question=f"Will {req.target_customer} pay monthly for {req.idea_title} without a live demo?",
                why_it_matters="A lifestyle business needs low-touch conversion.",
                validation_test_48h="Publish a one-page offer with the pitch and a pre-order button, then send it to people who described this pain.",
            ),
            OpenQuestionItem(
                question=f"Is the wedge real: {req.competitive_wedge or req.one_line_pitch or req.idea_title}?",
                why_it_matters="If buyers are already happy with the workaround, the MVP should not be built.",
                validation_test_48h="Ask five target buyers which workaround they use today and what would make them switch this month.",
            ),
            OpenQuestionItem(
                question="Does the 30-day MVP scope match the pain in the source post?",
                why_it_matters=req.core_problem[:240],
                validation_test_48h="Walk one buyer through a clickable mock of the three MVP steps and record whether they would try it this week.",
            ),
        ],
    )


def _fallback_risk_output(req: Stage2PRDRequest) -> RiskAnalystOutput:
    if not _is_certping(req):
        return _generic_risk_output(req)
    return RiskAnalystOutput(
        risks=[
            RiskItem(
                category="Market & Willingness-to-Pay Risk",
                risk_description="Small businesses complain about manual admin on Reddit but might resist adding another monthly subscription.",
                severity="High",
                likelihood="Medium",
                mitigation_strategy="Anchor pricing ($49/mo) directly against 1 hour of bookkeeper labor or 1 avoided compliance fine/scope leak ($500+), and offer a 14-day ROI guarantee.",
            ),
            RiskItem(
                category="Technical / AI Accuracy Risk",
                risk_description="LLM OCR misreads a blurry scanned PDF date or policy limit, leading to a false positive.",
                severity="High",
                likelihood="Medium",
                mitigation_strategy="Show side-by-side PDF highlight snippets next to extracted fields and flag any confidence score <90% for 1-click human verification.",
            ),
            RiskItem(
                category="Distribution & Cold-Start Risk",
                risk_description="Subreddit moderators may delete direct promotional links.",
                severity="Medium",
                likelihood="High",
                mitigation_strategy="Lead with helpful educational breakdowns, use direct 1-on-1 DMs to users who explicitly asked for a tool, and pair with niche cold email + SEO.",
            ),
            RiskItem(
                category="Platform / SMS Deliverability Risk",
                risk_description="A2P 10DLC SMS registration delays or carrier filtering on automated reminder texts.",
                severity="Medium",
                likelihood="Medium",
                mitigation_strategy="Start Day-1 MVP with magic-link emails + WhatsApp/Twilio toll-free verification while 10DLC processes.",
            ),
            RiskItem(
                category="Lifestyle & Support Burden Risk",
                risk_description="Non-technical SMB owners asking for manual white-glove onboarding that eats into the founder's 20 hr/wk cap.",
                severity="Medium",
                likelihood="Low",
                mitigation_strategy="Make onboarding 'Forward your existing files to setup@app.com' so the AI auto-populates their dashboard with zero manual configuration.",
            ),
        ],
        open_questions=[
            OpenQuestionItem(
                question="Will target buyers pay $49/mo self-serve without requiring a 30-minute live demo call?",
                why_it_matters="A true lifestyle business requires low-touch self-serve conversion rather than high-touch enterprise sales.",
                validation_test_48h="Launch a 1-page Carrd/Next.js landing page with an interactive 60-second Loom video and a '$29/mo Founding Member Pre-Order' Stripe button; send to 20 Redditors who commented on the pain point.",
            ),
            OpenQuestionItem(
                question="What percentage of real-world customer documents are blurry mobile photos vs. clean digital PDFs?",
                why_it_matters="Determines whether standard PDF text extraction suffices or if multimodal Gemini Vision OCR is needed on every upload.",
                validation_test_48h="Ask 5 target SMB owners to send 3 anonymized sample PDFs they received last week and benchmark Gemini 2.5 Flash extraction accuracy.",
            ),
            OpenQuestionItem(
                question="Do external recipients (subcontractors/clients) trust magic upload links sent via SMS/email?",
                why_it_matters="The product's core loop depends on third-party recipients completing the action without friction.",
                validation_test_48h="Include the customer's company name, logo, and reply-to email in the notification header and test response rate on 10 real requests.",
            ),
            OpenQuestionItem(
                question="Is monthly flat-tier pricing ($49/mo) preferred over usage-based per-document pricing?",
                why_it_matters="Impacts predictable MRR and customer churn.",
                validation_test_48h="A/B test pricing copy in 15 customer discovery DMs ('Would you rather pay $49/mo flat or $2 per tracked vendor?').",
            ),
        ],
    )
