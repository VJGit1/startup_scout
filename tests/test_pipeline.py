"""Offline tests for pain-point fetching, ranking, and PRD fallbacks."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from src.graph.stage1_graph import run_stage1_pipeline
from src.graph.stage2_graph import run_stage2_pipeline
from src.models import RedditPostInput, Stage1EvaluateRequest, Stage2PRDRequest
from src.tools.search import (
    fetch_hacker_news_pain_points,
    fetch_reddit_rss_pain_points,
    get_sample_reddit_posts,
    has_live_gemini_key,
)

FIXTURES = Path(__file__).parent / "fixtures"
HN_FIXTURE = json.loads((FIXTURES / "hn_search.json").read_text(encoding="utf-8"))

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Need a tool for receipts</title>
    <link href="https://www.reddit.com/r/smallbusiness/comments/abc123/need_a_tool/"/>
    <content type="html">Manual receipt chasing every month.</content>
  </entry>
</feed>
"""


def test_hacker_news_fetcher_uses_fixture_counts():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=HN_FIXTURE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        posts = fetch_hacker_news_pain_points(http_client=client)

    assert len(posts) == 1
    assert posts[0].post_id == "hn_story_1001"
    assert posts[0].source_platform == "Hacker News"
    assert posts[0].upvotes == 42
    assert posts[0].num_comments == 11
    assert posts[0].url == "https://news.ycombinator.com/item?id=1001"


def test_reddit_rss_encodes_query_and_does_not_invent_upvotes():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text=RSS_FEED)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        posts = fetch_reddit_rss_pain_points(
            subreddits=["smallbusiness", "freelance"],
            http_client=client,
        )

    assert len(requested) == 2
    assert all("q=manual+OR+software" in url for url in requested)
    assert "smallbusiness" in requested[0]
    assert "freelance" in requested[1]
    assert posts[0].post_id == "abc123"
    assert posts[0].upvotes == 0
    assert posts[0].num_comments == 0


def test_curated_pipeline_ranks_fixture_ideas_and_drops_airline():
    response = run_stage1_pipeline(
        Stage1EvaluateRequest(posts=get_sample_reddit_posts(), fetch_live=False)
    )

    top_blob = " ".join(f"{idea.idea_id} {idea.idea_title}" for idea in response.top_3_ideas).lower()
    assert "airline" not in top_blob
    assert sum(name in top_blob for name in ("certping", "scopeguard", "pausesave")) >= 2
    assert response.agent_mode == "fallback"
    assert response.source_used == "provided"
    assert response.all_evaluated_ideas[0].source_platform == "curated"
    assert response.google_sheets_rows[0]["Source_Platform"] == "curated"
    assert any(error.startswith("extract_ideas:") for error in response.node_errors)


def test_unknown_post_is_not_scored_as_airline():
    post = RedditPostInput(
        title="Ask HN: I wish there was a tool to reconcile marketplace payouts with the bank",
        selftext="We spend hours every week on this manual spreadsheet.",
        source_platform="Hacker News",
        url="https://news.ycombinator.com/item?id=42",
        upvotes=40,
    )
    response = run_stage1_pipeline(Stage1EvaluateRequest(posts=[post], fetch_live=False))
    idea = response.all_evaluated_ideas[0]
    assert idea.research.estimated_startup_cost_usd != 5_000_000
    assert "software" in idea.idea_id
    assert idea.source_platform == "Hacker News"


def test_empty_posts_request_hacker_news_source(monkeypatch):
    calls: dict[str, object] = {}

    def fake_fetch(source: str = "hn", subreddits=None):
        calls["source"] = source
        calls["subreddits"] = list(subreddits or [])
        return [
            RedditPostInput(
                title="Wish there was a tool for invoice reminders",
                selftext="I am tired of manually emailing clients about unpaid invoices.",
                source_platform="Hacker News",
                url="https://news.ycombinator.com/item?id=77",
                upvotes=30,
            )
        ]

    monkeypatch.setattr("src.graph.stage1_graph.fetch_pain_points", fake_fetch)
    response = run_stage1_pipeline(
        Stage1EvaluateRequest(posts=[], source="hn", fetch_live=True)
    )

    assert calls["source"] == "hn"
    assert response.source_used == "hn"
    assert response.total_posts_analyzed == 1


def test_hacker_news_fetcher_stops_at_three_posts():
    hits = [
        {
            "objectID": str(i),
            "title": f"Wish there was a tool {i}",
            "story_text": "Tired of doing this manually.",
            "points": 1,
            "num_comments": 0,
        }
        for i in range(6)
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hits": hits})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        posts = fetch_hacker_news_pain_points(http_client=client)

    assert len(posts) == 3
    assert [post.post_id for post in posts] == ["hn_story_0", "hn_story_1", "hn_story_2"]


def test_failed_live_fetch_does_not_substitute_fixture_posts(monkeypatch):
    monkeypatch.setattr("src.graph.stage1_graph.fetch_pain_points", lambda **_kwargs: [])
    response = run_stage1_pipeline(
        Stage1EvaluateRequest(posts=[], source="hn", fetch_live=True)
    )

    assert response.source_used == "hn"
    assert response.total_posts_analyzed == 0
    assert response.top_3_ideas == []
    assert response.google_sheets_rows == []
    assert any("zero items" in error for error in response.node_errors)
    assert not any("reddit.com" in error for error in response.node_errors)


def test_stage2_fallback_describes_the_approved_idea():
    response = run_stage2_pipeline(
        Stage2PRDRequest(
            idea_id="idea-payout",
            idea_title="PayoutReconcile",
            one_line_pitch="Match Stripe payouts to the bank.",
            core_problem="Hours lost reconciling payouts in a spreadsheet.",
            target_customer="Indie SaaS founders",
            competitive_wedge="CSV in, matched ledger out",
            bottom_up_tam_summary="20000 buyers x $348/yr",
            startup_cost_summary="$400 under the founder budget",
            founder_fit_summary="Moderate fit for the configured founder",
        )
    )
    markdown = response.google_doc_markdown
    assert "PayoutReconcile" in markdown
    assert "Certificate of Insurance" not in markdown
    assert "Founder Profile:" in markdown
    assert "{{" not in markdown
    assert response.agent_mode == "fallback"
    assert response.source_used == "approved_idea"


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI") != "1" or not has_live_gemini_key(),
    reason="Set GEMINI_API_KEY and RUN_LIVE_GEMINI=1 to call Gemini",
)
def test_live_gemini_structured_output():
    from pydantic import BaseModel

    from src.tools.search import invoke_structured_llm

    class Echo(BaseModel):
        answer: str

    result = invoke_structured_llm(
        "Return JSON matching the schema.",
        "Set answer to the single word ready.",
        Echo,
    )
    assert result.answer
