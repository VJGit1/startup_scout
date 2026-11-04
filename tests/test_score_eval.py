"""Offline checks that ranking, the weighted formula, and article URLs stay fixed."""

from __future__ import annotations

import json
from pathlib import Path

from src.graph.stage1_graph import CandidateIdeaDraft, _overlay_post_metadata, run_stage1_pipeline
from src.models import RedditPostInput, Stage1EvaluateRequest
from src.tools.search import get_sample_reddit_posts

CASES = json.loads((Path(__file__).parent / "fixtures" / "score_cases.json").read_text(encoding="utf-8"))


def _curated_response():
    return run_stage1_pipeline(
        Stage1EvaluateRequest(posts=get_sample_reddit_posts(), fetch_live=False)
    )


def _matching_order(ideas) -> list[str]:
    found: list[str] = []
    expected = CASES["expected_rank_order"]
    for idea in ideas:
        for token in expected:
            if token in idea.idea_id and token not in found:
                found.append(token)
    return found


def test_eval_sample_ideas_keep_expected_order():
    response = _curated_response()
    assert _matching_order(response.all_evaluated_ideas) == CASES["expected_rank_order"]
    assert [step.name for step in response.trace] == ["Extract", "Research", "Founder fit", "Rank"]
    assert all(step.mode == "fallback" and step.elapsed_ms >= 0 for step in response.trace)


def test_eval_airline_is_excluded_from_top_3():
    response = _curated_response()
    top_blob = " ".join(idea.idea_id for idea in response.top_3_ideas).lower()
    for token in CASES["excluded_from_top3"]:
        assert token not in top_blob
    assert _matching_order(response.top_3_ideas) == CASES["expected_rank_order"][:3]


def test_eval_weighted_total_matches_formula():
    response = _curated_response()
    weights = CASES["weights"]
    for idea in response.all_evaluated_ideas:
        scores = idea.scores
        total = 10.0 * sum(weights[key] * getattr(scores, key) for key in weights)
        assert scores.weighted_total_score == round(total, 1)


def test_eval_fetched_article_url_replaces_model_url():
    case = CASES["url_pin"]
    post = RedditPostInput(
        post_id=case["post_id"],
        source_platform="Hacker News",
        subreddit="Ask HN",
        title=case["title"],
        url=case["article_url"],
        discussion_url=case["discussion_url"],
    )
    draft = CandidateIdeaDraft(
        idea_id="widget",
        idea_title="Widget",
        one_line_pitch="A widget.",
        core_problem="Widgets are hard.",
        target_customer="Builders",
        source_subreddit="Ask HN",
        source_reddit_title=case["title"],
        source_reddit_url=case["model_url"],
    )
    fixed = _overlay_post_metadata([draft], [post])
    assert fixed[0].source_reddit_url == case["article_url"]
    assert fixed[0].discussion_url == case["discussion_url"]


def _draft(title: str, url: str) -> CandidateIdeaDraft:
    return CandidateIdeaDraft(
        idea_id=title.lower().replace(" ", "-"),
        idea_title=title,
        one_line_pitch="A tool.",
        core_problem="The old workflow is slow.",
        target_customer="Builders",
        source_subreddit="Ask HN",
        source_reddit_title=title,
        source_reddit_url=url,
    )


def test_eval_reordered_ideas_keep_their_own_article():
    formstep = RedditPostInput(
        source_platform="Hacker News",
        title="Show HN: Formstep",
        url="https://formstep.io",
        discussion_url="https://news.ycombinator.com/item?id=1",
    )
    instance = RedditPostInput(
        source_platform="Hacker News",
        title="Show HN: Instance",
        url="https://github.com/groverburger/instance",
        discussion_url="https://news.ycombinator.com/item?id=2",
    )
    swapped = [
        _draft("Show HN: Instance", "https://not-a-real-article.example/instance"),
        _draft("Show HN: Formstep", "https://not-a-real-article.example/formstep"),
    ]
    fixed = _overlay_post_metadata(swapped, [formstep, instance])
    assert fixed[0].source_reddit_url == "https://github.com/groverburger/instance"
    assert fixed[1].source_reddit_url == "https://formstep.io"

    rewritten = [
        _draft("A game engine", "https://not-a-real-article.example/engine"),
        _draft("A form tool", "https://not-a-real-article.example/form"),
    ]
    untouched = _overlay_post_metadata(rewritten, [formstep, instance])
    assert untouched[0].source_reddit_url == "https://not-a-real-article.example/engine"
    assert untouched[1].source_reddit_url == "https://not-a-real-article.example/form"
