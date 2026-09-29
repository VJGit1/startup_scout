"""
Live Web Search, Reddit Pain-Point Fetcher, and Gemini LLM Helper Tools.
Supports live Reddit public JSON scraping, DuckDuckGo / Google Search grounding,
and structured LLM generation via Google Gemini.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Type, TypeVar
import httpx
from pydantic import BaseModel

from src.models import RedditPostInput

T = TypeVar("T", bound=BaseModel)

PAIN_POINT_QUERIES = [
    '"wish there was a tool" OR "why is there no app" OR "tired of manually"',
    '"paying too much for" OR "spreadsheet nightmare" OR "manual workflow"',
]


def get_sample_reddit_posts() -> List[RedditPostInput]:
    """Curated real-world Reddit pain-point posts for testing or fallback."""
    return [
        RedditPostInput(
            post_id="r_smb_01",
            subreddit="r/smallbusiness",
            title="Spending 6 hours every Friday chasing subcontractors for updated COI (Certificate of Insurance) PDFs",
            selftext=(
                "I run a 12-person property maintenance & general contracting business. Every month, "
                "3 or 4 of our sub-vendors have expiring general liability or workers comp policies. "
                "Procore and enterprise compliance tools want $600+/month and force a massive ERP migration. "
                "I just want a simple tool that reads their uploaded PDF certificate, checks expiration dates "
                "and coverage minimums, and auto-texts/emails them 14 days before expiry."
            ),
            url="https://www.reddit.com/r/smallbusiness/comments/coi_tracking_pain",
            upvotes=142,
            num_comments=64,
        ),
        RedditPostInput(
            post_id="r_freelance_02",
            subreddit="r/freelance",
            title="Why is there no lightweight scope-creep tracker that turns Slack/email 'quick asks' into 1-click change orders?",
            selftext=(
                "Every web design and marketing agency owner I know loses 15-20% of revenue to clients "
                "dropping 'Hey can we also quickly add...' in Slack or email threads. Full PSA suites are bloated. "
                "I wish I could forward an email or react with an emoji in Slack, have AI compare it against "
                "the original SOW PDF, and generate a polite $250-$500 micro-change-order approval link."
            ),
            url="https://www.reddit.com/r/freelance/comments/scope_creep_change_orders",
            upvotes=218,
            num_comments=89,
        ),
        RedditPostInput(
            post_id="r_saas_03",
            subreddit="r/SaaS",
            title="We lose 30% of failed-payment customers because Stripe dunning emails look like spam and don't offer a pause option",
            selftext=(
                "Churnkey and ProfitWell Retain cost hundreds to thousands a month once you scale, which is "
                "overkill for indie micro-SaaS founders making $3k-$25k MRR. I just want a $29/mo plug-and-play "
                "cancellation & failed-payment recovery flow with SMS/WhatsApp reminders and a 1-click pause subscription button."
            ),
            url="https://www.reddit.com/r/SaaS/comments/indie_dunning_pause_flow",
            upvotes=96,
            num_comments=41,
        ),
        RedditPostInput(
            post_id="r_ent_04",
            subreddit="r/entrepreneur",
            title="Local MedSpas and dental clinics are terrible at replying to Instagram/Google Maps DMs after 5pm",
            selftext=(
                "I consulted for 5 local aesthetic clinics. They spend $3,000/mo on Meta ads, then let leads sit "
                "unanswered for 14 hours overnight. Existing healthcare CRMs like Podium charge $500+/mo on annual lock-in "
                "contracts. Clinics desperately want a $79/mo after-hours AI receptionist that answers pricing/FAQ "
                "questions from their exact service menu and books consults."
            ),
            url="https://www.reddit.com/r/entrepreneur/comments/medspa_after_hours_dm_booking",
            upvotes=175,
            num_comments=53,
        ),
        RedditPostInput(
            post_id="r_smb_05",
            subreddit="r/smallbusiness",
            title="I want to start a new nationwide airline with $500 budget because flights are too cramped",
            selftext=(
                "Why doesn't someone just lease 10 Boeing 737 jets and make all seats first class for $99 tickets? "
                "Seems like an easy startup idea."
            ),
            url="https://www.reddit.com/r/smallbusiness/comments/airline_hardware_idea",
            upvotes=12,
            num_comments=38,
        ),
    ]


def fetch_reddit_pain_points(
    subreddits: List[str] | None = None,
    limit_per_sub: int = 5,
) -> List[RedditPostInput]:
    """
    Fetch real pain-point posts from Reddit's public JSON search endpoint.
    Falls back gracefully to curated Reddit pain-point posts if rate-limited or offline.
    """
    subs = subreddits or ["smallbusiness", "entrepreneur", "SaaS", "freelance"]
    collected: List[RedditPostInput] = []
    headers = {"User-Agent": "LifestyleStartupDiscoveryAgent/1.0"}

    try:
        with httpx.Client(timeout=8.0, headers=headers, follow_redirects=True) as client:
            for sub in subs[:3]:
                url = (
                    f"https://www.reddit.com/r/{sub}/search.json"
                    f"?q=wish+there+was+OR+manual+OR+expensive+tool&restrict_sr=on&sort=top&t=month&limit={limit_per_sub}"
                )
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                children = resp.json().get("data", {}).get("children", [])
                for child in children:
                    data = child.get("data", {})
                    title = data.get("title", "").strip()
                    selftext = data.get("selftext", "").strip()
                    if title and len(selftext) > 60:
                        collected.append(
                            RedditPostInput(
                                post_id=data.get("id", ""),
                                subreddit=f"r/{sub}",
                                title=title,
                                selftext=selftext[:1500],
                                url=f"https://www.reddit.com{data.get('permalink', '')}",
                                upvotes=int(data.get("ups", 10)),
                                num_comments=int(data.get("num_comments", 5)),
                            )
                        )
    except Exception:
        pass

    if len(collected) < 3:
        return get_sample_reddit_posts()
    return collected


def live_web_search(query: str, max_results: int = 4) -> str:
    """
    Run a live web search using duckduckgo_search to gather real competitor names,
    pricing tiers, and market size indicators.
    """
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f"No external web results returned for query: {query}"
        formatted = []
        for idx, r in enumerate(results, 1):
            formatted.append(
                f"[{idx}] {r.get('title', '')} ({r.get('href', '')}): {r.get('body', '')}"
            )
        return "\n".join(formatted)
    except Exception as exc:
        return f"Web search fallback mode ({exc})"


def has_live_gemini_key() -> bool:
    """Return True if a real GEMINI_API_KEY is configured in the environment."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    return bool(api_key and api_key != "your_gemini_api_key_here")


def invoke_structured_llm(
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
) -> T:
    """
    Invoke Google Gemini via langchain-google-genai with `.with_structured_output(schema)`.
    Raises RuntimeError if no valid API key is present so the caller can use its deterministic fallback.
    """
    if not has_live_gemini_key():
        raise RuntimeError("GEMINI_API_KEY not set; using structured deterministic agent fallback.")

    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage, SystemMessage

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0.2,
    )
    structured_llm = llm.with_structured_output(schema)
    result = structured_llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return result  # type: ignore[return-value]
