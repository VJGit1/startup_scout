"""
Pydantic v2 Data Models for the Two-Stage Lifestyle Startup Discovery & PRD Pipeline.
Designed for seamless JSON exchange between n8n, Google Sheets, Google Docs, and LangGraph.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class RedditPostInput(BaseModel):
    """Input representation of a scraped Reddit post from n8n or direct scraper."""
    post_id: Optional[str] = Field(default=None, description="Reddit post ID")
    subreddit: str = Field(default="r/smallbusiness", description="Subreddit name")
    title: str = Field(..., description="Title of the Reddit post")
    selftext: str = Field(default="", description="Body text of the Reddit post")
    url: str = Field(default="", description="Permalink URL to the Reddit post")
    upvotes: int = Field(default=10, description="Number of upvotes")
    num_comments: int = Field(default=5, description="Number of comments")


class BottomUpTAM(BaseModel):
    """Bottom-Up TAM calculation for a niche lifestyle business."""
    target_buyer_segment: str = Field(..., description="Specific niche customer segment")
    estimated_target_users: int = Field(..., description="Estimated reachable buyers in niche (N)")
    monthly_price_usd: float = Field(..., description="Recommended monthly price ($/mo)")
    annual_price_usd: float = Field(..., description="Annual revenue per user ($/yr = monthly * 12)")
    bottom_up_tam_usd: float = Field(..., description="Bottom-Up TAM ($ USD = N * Annual Price)")
    customers_for_10k_mrr: int = Field(..., description="Customers needed to reach $10,000 MRR lifestyle goal")
    tam_formula_explanation: str = Field(..., description="Human-readable calculation formula and source rationale")


class CompetitorInfo(BaseModel):
    """Direct or indirect competitor identified during competitive research."""
    name: str = Field(..., description="Competitor product or workaround name")
    pricing: str = Field(..., description="Competitor pricing tier")
    weakness_or_gap: str = Field(..., description="Why Reddit users are still unhappy with this option")


class CompetitiveResearchSummary(BaseModel):
    """Competitive research and initial startup cost estimate."""
    competitors: List[CompetitorInfo] = Field(default_factory=list)
    competitive_wedge: str = Field(..., description="Our specific lifestyle business wedge against incumbents")
    estimated_startup_cost_usd: float = Field(..., description="Total initial cost ($ USD) to build & launch MVP")
    startup_cost_breakdown: str = Field(..., description="Itemized Month 1-3 costs (hosting, APIs, domain, GTM)")
    tam: BottomUpTAM


class FounderMarketFitResult(BaseModel):
    """Output of the Founder-Market Fit Agent."""
    founder_fit_score: float = Field(..., ge=1.0, le=10.0, description="Score from 1.0 to 10.0")
    fit_verdict: Literal["Strong Fit", "Moderate Fit", "Poor Fit"] = Field(..., description="Categorical fit verdict")
    strengths: List[str] = Field(default_factory=list, description="Why this founder is well-suited")
    blind_spots: List[str] = Field(default_factory=list, description="Gaps or risks for this founder")
    fit_rationale: str = Field(..., description="Concise summary for Google Sheets and PRD")


class LifestyleRubricScores(BaseModel):
    """Individual 1-10 scores across the 5 Lifestyle Business Rubric criteria."""
    pain_severity_score: float = Field(..., ge=1.0, le=10.0, description="Weight 25%")
    low_startup_cost_score: float = Field(..., ge=1.0, le=10.0, description="Weight 25%")
    competition_gap_score: float = Field(..., ge=1.0, le=10.0, description="Weight 20%")
    tam_sweet_spot_score: float = Field(..., ge=1.0, le=10.0, description="Weight 15%")
    founder_fit_score: float = Field(..., ge=1.0, le=10.0, description="Weight 15%")
    weighted_total_score: float = Field(..., ge=0.0, le=100.0, description="Weighted score out of 100")


class EvaluatedStartupIdea(BaseModel):
    """Full Stage 1 evaluation record ready to be written as a row in Google Sheets."""
    idea_id: str = Field(..., description="Unique slug/ID for the idea")
    idea_title: str = Field(..., description="Name and catchy title of the lifestyle startup idea")
    one_line_pitch: str = Field(..., description="Concise 1-sentence value pitch")
    core_problem: str = Field(..., description="Core pain point extracted from Reddit")
    target_customer: str = Field(..., description="Specific buyer persona")
    source_subreddit: str = Field(..., description="Source subreddit")
    source_reddit_title: str = Field(..., description="Original Reddit thread title")
    source_reddit_url: str = Field(..., description="Original Reddit thread URL")
    research: CompetitiveResearchSummary
    founder_fit: FounderMarketFitResult
    scores: LifestyleRubricScores
    evaluator_verdict: str = Field(..., description="Why the Startup Evaluator ranked this idea where it did")
    rank: int = Field(..., description="Overall rank (1 = best)")
    is_top_3: bool = Field(..., description="True if picked in the Top 3 by the Startup Evaluator Agent")
    approval_status: str = Field(
        default="Backlog",
        description="Google Sheet status column: 'Pending Review (Top 3)', 'Approved', 'PRD Generated', or 'Backlog'",
    )

    def to_google_sheet_row(self) -> Dict[str, Any]:
        """Flatten into a clean dictionary matching Google Sheets columns for n8n."""
        comp_names = ", ".join(f"{c.name} ({c.pricing})" for c in self.research.competitors)
        return {
            "Rank": self.rank,
            "Is_Top_3": "YES (Top 3)" if self.is_top_3 else "No",
            "Approval_Status": self.approval_status,
            "Idea_ID": self.idea_id,
            "Idea_Title": self.idea_title,
            "One_Line_Pitch": self.one_line_pitch,
            "Core_Problem": self.core_problem,
            "Target_Customer": self.target_customer,
            "Total_Score_100": round(self.scores.weighted_total_score, 1),
            "Bottom_Up_TAM_USD": f"${self.research.tam.bottom_up_tam_usd:,.0f}/yr",
            "TAM_Formula": self.research.tam.tam_formula_explanation,
            "Customers_For_10k_MRR": self.research.tam.customers_for_10k_mrr,
            "Startup_Cost_USD": f"${self.research.estimated_startup_cost_usd:,.0f}",
            "Startup_Cost_Breakdown": self.research.startup_cost_breakdown,
            "Competitors": comp_names,
            "Competitive_Wedge": self.research.competitive_wedge,
            "Founder_Fit_Score_10": round(self.founder_fit.founder_fit_score, 1),
            "Founder_Fit_Verdict": self.founder_fit.fit_verdict,
            "Founder_Fit_Rationale": self.founder_fit.fit_rationale,
            "Evaluator_Verdict": self.evaluator_verdict,
            "Source_Subreddit": self.source_subreddit,
            "Source_Reddit_Title": self.source_reddit_title,
            "Source_Reddit_URL": self.source_reddit_url,
            "Google_Doc_PRD_URL": "",
        }


class Stage1EvaluateRequest(BaseModel):
    """Request payload sent from n8n Stage 1 workflow (or CLI)."""
    posts: List[RedditPostInput] = Field(
        default_factory=list,
        description="Scraped Reddit posts from n8n. If empty and fetch_live_reddit=True, backend scrapes Reddit.",
    )
    fetch_live_reddit: bool = Field(
        default=False,
        description="If true and posts is empty, automatically scrape Reddit pain-point threads.",
    )
    subreddits: List[str] = Field(
        default_factory=lambda: ["smallbusiness", "entrepreneur", "SaaS", "freelance"],
        description="Subreddits to query when fetch_live_reddit=True",
    )
    founder_profile_override: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional inline Founder Profile override",
    )


class Stage1EvaluateResponse(BaseModel):
    """Response returned to n8n Stage 1 workflow."""
    total_posts_analyzed: int
    top_3_ideas: List[EvaluatedStartupIdea]
    all_evaluated_ideas: List[EvaluatedStartupIdea]
    google_sheets_rows: List[Dict[str, Any]]


# ============================================================================
# Stage 2 Models: Deep Research, PM Agent (Kano Model), Risk Agent -> PRD Doc
# ============================================================================


class KanoFeatureItem(BaseModel):
    """Feature prioritized using the Kano Model and mapped to Reddit pain points."""
    feature_name: str
    kano_category: Literal["Basic Expectation", "Performance Feature", "Delighter"]
    mapped_reddit_pain_point: str
    user_impact: str
    build_effort_days: int
    mvp_phase: Literal["Day-1 MVP (<30 Days)", "v1.1 Fast Follow", "v2.0 Future"]


class RiskItem(BaseModel):
    """Risk identified by the Risk Analysis Agent."""
    category: str
    risk_description: str
    severity: Literal["High", "Medium", "Low"]
    likelihood: Literal["High", "Medium", "Low"]
    mitigation_strategy: str


class OpenQuestionItem(BaseModel):
    """Open question and 48-hour validation experiment."""
    question: str
    why_it_matters: str
    validation_test_48h: str


class Stage2PRDRequest(BaseModel):
    """Request payload sent from n8n Stage 2 when a user approves an idea in Google Sheets."""
    idea_id: Optional[str] = Field(default="approved-idea-1")
    idea_title: str = Field(..., description="Approved startup idea title from Google Sheet")
    one_line_pitch: str = Field(default="", description="One line pitch from Google Sheet")
    core_problem: str = Field(..., description="Core problem statement from Google Sheet")
    target_customer: str = Field(default="Small business owners & prosumers")
    source_subreddit: str = Field(default="r/smallbusiness")
    source_reddit_title: str = Field(default="")
    source_reddit_url: str = Field(default="")
    bottom_up_tam_summary: str = Field(default="")
    startup_cost_summary: str = Field(default="")
    competitors_summary: str = Field(default="")
    competitive_wedge: str = Field(default="")
    founder_fit_summary: str = Field(default="")
    founder_profile_override: Optional[Dict[str, Any]] = Field(default=None)


class PRDContentSections(BaseModel):
    """Structured sections authored by the Research, PM, and Risk Analysis agents."""
    problem_statement: str
    competition_and_tam_analysis: str
    value_proposition: str
    mvp_scope_and_architecture: str
    kano_features: List[KanoFeatureItem]
    gtm_and_pricing_strategy: str
    risks: List[RiskItem]
    open_questions: List[OpenQuestionItem]


class Stage2PRDResponse(BaseModel):
    """Response returned to n8n Stage 2 workflow to create the Google Doc PRD."""
    idea_id: str
    document_title: str
    sections: PRDContentSections
    google_doc_markdown: str = Field(
        ...,
        description="Complete formatted PRD document ready to write into a Google Doc",
    )
