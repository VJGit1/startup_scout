"""
Live Web Search, Reddit Pain-Point Fetcher, and Gemini LLM Helper Tools.
Supports live Reddit public JSON scraping, DuckDuckGo / Google Search grounding,
and structured LLM generation via Google Gemini.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, Callable, List, Type, TypeVar
from urllib.parse import urlencode
import httpx
from pydantic import BaseModel

from src.models import RedditPostInput

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)

PAIN_POINT_QUERIES = [
    '"wish there was a tool" OR "why is there no app" OR "tired of manually"',
    '"paying too much for" OR "spreadsheet nightmare" OR "manual workflow"',
]


def get_sample_reddit_posts() -> List[RedditPostInput]:
    """Offline fixture posts. The Reddit URLs are not real threads."""
    return [
        RedditPostInput(
            post_id="r_smb_01",
            source_platform="curated",
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
            source_platform="curated",
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
            source_platform="curated",
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
            source_platform="curated",
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
            source_platform="curated",
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


def clean_html(raw_html: str) -> str:
    """Strip basic HTML tags and unescape common HTML entities from HN comments."""
    if not raw_html:
        return ""
    import html as html_lib
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html_lib.unescape(text)
    return " ".join(text.split())


def _optional_count(value: Any) -> int:
    """Use a real engagement count when the source provides one."""
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _reddit_post_id(link: str) -> str:
    match = re.search(r"/comments/([^/]+)/", link or "")
    if match:
        return match.group(1)
    return "rss_item"


def _log_fetch_error(operation: str, exc: Exception) -> None:
    logger.warning("%s: %s: %s", operation, type(exc).__name__, exc)


def fetch_hacker_news_pain_points(
    queries: List[str] | None = None,
    limit_per_query: int = 4,
    http_client: httpx.Client | None = None,
    max_posts: int = 3,
) -> List[RedditPostInput]:
    """
    Fetch high-signal B2B and prosumer pain points from Hacker News via the official Algolia API.
    Stops at max_posts so one Gemini free-tier day can score the batch.
    Returns an empty list when the API is unreachable.
    """
    search_queries = queries or [
        "Ask HN tool you wish existed",
        "Ask HN tedious workflow",
        "wish there was a tool",
        "tired of manually",
    ]
    collected: List[RedditPostInput] = []
    seen_ids: set[str] = set()

    def _collect(client: httpx.Client) -> None:
        for query in search_queries:
            try:
                resp = client.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={"query": query, "tags": "story", "hitsPerPage": limit_per_query},
                )
                resp.raise_for_status()
            except Exception as exc:
                _log_fetch_error("fetch_hacker_news_pain_points", exc)
                continue
            for hit in resp.json().get("hits", []):
                object_id = str(hit.get("objectID", ""))
                if not object_id or object_id in seen_ids:
                    continue
                seen_ids.add(object_id)
                title = (hit.get("title") or "").strip()
                if not title:
                    continue
                body = clean_html(hit.get("story_text") or "")
                collected.append(
                    RedditPostInput(
                        post_id=f"hn_story_{object_id}",
                        source_platform="Hacker News",
                        subreddit="Ask HN",
                        title=title,
                        selftext=body[:1500] if body else f"Hacker News discussion: {title}",
                        url=f"https://news.ycombinator.com/item?id={object_id}",
                        upvotes=_optional_count(hit.get("points")),
                        num_comments=_optional_count(hit.get("num_comments")),
                    )
                )
                if len(collected) >= max_posts:
                    return
        try:
            comment_resp = client.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": "wish there was a tool", "tags": "comment", "hitsPerPage": 5},
            )
            comment_resp.raise_for_status()
        except Exception as exc:
            _log_fetch_error("fetch_hacker_news_pain_points", exc)
            return
        if len(collected) >= max_posts:
            return
        for comment in comment_resp.json().get("hits", []):
            comment_id = str(comment.get("objectID", ""))
            if not comment_id or comment_id in seen_ids:
                continue
            seen_ids.add(comment_id)
            comment_text = clean_html(comment.get("comment_text") or "")
            if len(comment_text) <= 40:
                continue
            parent_title = comment.get("story_title") or "HN Discussion"
            collected.append(
                RedditPostInput(
                    post_id=f"hn_comment_{comment_id}",
                    source_platform="Hacker News",
                    subreddit=f"HN Comment ({parent_title[:30]})",
                    title=f"User Need: {comment_text[:90]}...",
                    selftext=comment_text[:1500],
                    url=f"https://news.ycombinator.com/item?id={comment_id}",
                    upvotes=_optional_count(comment.get("points")),
                    num_comments=0,
                )
            )
            if len(collected) >= max_posts:
                return

    try:
        if http_client is not None:
            _collect(http_client)
        else:
            with httpx.Client(timeout=9.0, headers={"User-Agent": "LifestyleStartupScout/1.0"}) as client:
                _collect(client)
    except Exception as exc:
        _log_fetch_error("fetch_hacker_news_pain_points", exc)
    return collected


def fetch_reddit_rss_pain_points(
    subreddits: List[str] | None = None,
    query: str = "manual OR software",
    limit_per_sub: int = 4,
    http_client: httpx.Client | None = None,
) -> List[RedditPostInput]:
    """
    Fetch posts via public Reddit Atom feeds.
    Best-effort only: a failed subreddit is logged and skipped. Upvotes are left at 0
    because the feed does not include them.
    """
    import xml.etree.ElementTree as ET

    subs = subreddits or ["smallbusiness", "freelance", "SaaS", "entrepreneur"]
    collected: List[RedditPostInput] = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    query_string = urlencode({"q": query, "restrict_sr": "on", "sort": "top", "t": "month"})

    def _collect(client: httpx.Client) -> None:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for sub in subs:
            url = f"https://www.reddit.com/r/{sub}/search.rss?{query_string}"
            try:
                resp = client.get(url)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
            except Exception as exc:
                _log_fetch_error(f"fetch_reddit_rss_pain_points r/{sub}", exc)
                continue
            entries = root.findall("atom:entry", ns)[:limit_per_sub]
            for entry in entries:
                title_elem = entry.find("atom:title", ns)
                link_elem = entry.find("atom:link", ns)
                content_elem = entry.find("atom:content", ns)
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                link = link_elem.attrib.get("href", "") if link_elem is not None else ""
                raw_content = content_elem.text if content_elem is not None and content_elem.text else ""
                if not title:
                    continue
                collected.append(
                    RedditPostInput(
                        post_id=_reddit_post_id(link),
                        source_platform="Reddit RSS",
                        subreddit=f"r/{sub}",
                        title=title,
                        selftext=clean_html(raw_content)[:1500],
                        url=link,
                        upvotes=0,
                        num_comments=0,
                    )
                )

    try:
        if http_client is not None:
            _collect(http_client)
        else:
            with httpx.Client(timeout=8.0, headers=headers, follow_redirects=True) as client:
                _collect(client)
    except Exception as exc:
        _log_fetch_error("fetch_reddit_rss_pain_points", exc)
    return collected


def fetch_pain_points(
    source: str = "hn",
    subreddits: List[str] | None = None,
) -> List[RedditPostInput]:
    """
    Unified zero-cost pain-point fetcher.
    Source options:
      - 'hn': Hacker News Algolia API
      - 'reddit_rss': Reddit public XML feeds (best effort)
      - 'all': Hacker News plus Reddit RSS
      - 'curated': Curated high-signal sample dataset
    Returns an empty list when a live source yields nothing. The pipeline records that
    and does not replace the miss with fixture posts.
    """
    if source == "curated":
        return get_sample_reddit_posts()
    if source == "reddit_rss":
        return fetch_reddit_rss_pain_points(subreddits=subreddits)
    if source == "all":
        return fetch_hacker_news_pain_points() + fetch_reddit_rss_pain_points(subreddits=subreddits)
    return fetch_hacker_news_pain_points()


def _run_with_timeout(fn: Callable[[], Any], timeout_seconds: float) -> Any:
    """Run fn on a daemon thread so a hung call cannot stall the pipeline."""
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except Exception as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TimeoutError(f"timed out after {timeout_seconds}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


_web_search_failure: str | None = None


def live_web_search(query: str, max_results: int = 4) -> str:
    """
    Run a live web search using duckduckgo_search to gather real competitor names,
    pricing tiers, and market size indicators. Gives up after 15 seconds.
    The first failure is reused for the rest of the process.
    """
    global _web_search_failure
    if _web_search_failure is not None:
        return _web_search_failure

    def _search() -> list:
        from duckduckgo_search import DDGS

        try:
            client = DDGS(timeout=10)
        except TypeError:
            client = DDGS()
        with client as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        results = _run_with_timeout(_search, 15)
        if not results:
            return f"No external web results returned for query: {query}"
        formatted = []
        for idx, r in enumerate(results, 1):
            formatted.append(
                f"[{idx}] {r.get('title', '')} ({r.get('href', '')}): {r.get('body', '')}"
            )
        return "\n".join(formatted)
    except Exception as exc:
        _log_fetch_error("live_web_search", exc)
        _web_search_failure = f"Web search fallback mode ({type(exc).__name__}: {exc})"
        return _web_search_failure


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
        max_retries=0,
    )
    structured_llm = llm.with_structured_output(schema)
    result = structured_llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return coerce_structured_result(result, schema)


def coerce_structured_result(result: Any, schema: Type[T]) -> T:
    """Validate a Gemini structured result into the requested Pydantic model."""
    if isinstance(result, schema):
        return result
    if isinstance(result, dict):
        return schema.model_validate(result)
    if result is None:
        raise ValueError(f"LLM returned None for {schema.__name__}")
    raise TypeError(f"LLM returned {type(result).__name__}, expected {schema.__name__}")
