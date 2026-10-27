"""The local results page, saved runs, and founder profile form."""

from pathlib import Path

from fastapi.testclient import TestClient

from src.board import archive_stage1, is_live_article_url, source_html, update_founder_profile
from src.graph.stage1_graph import run_stage1_pipeline
from src.main import app
from src.models import Stage1EvaluateRequest
from src.skill_loader import load_founder_profile
from src.tools.search import get_sample_reddit_posts


def test_sample_reddit_links_are_not_clickable_and_hn_links_are():
    fake = "https://www.reddit.com/r/freelance/comments/scope_creep_change_orders"
    live = "https://news.ycombinator.com/item?id=12345"
    assert is_live_article_url(fake) is False
    assert is_live_article_url(live) is True
    assert "<a " not in source_html({"source_reddit_url": fake, "source_reddit_title": "Sample"})
    assert f"href='{live}'" in source_html({"source_reddit_url": live, "source_reddit_title": "Ask HN"})
    article = source_html(
        {
            "source_reddit_url": "https://example.com/widget",
            "source_reddit_title": "Show HN: Widget",
            "discussion_url": live,
        }
    )
    assert "href='https://example.com/widget'" in article
    assert f"href='{live}'" in article
    assert "Hacker News thread" in article


def test_results_page_shows_score_parts_and_approve_writes_a_plan(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    response = run_stage1_pipeline(
        Stage1EvaluateRequest(posts=get_sample_reddit_posts(), fetch_live=False)
    )
    (tmp_path / "stage1_evaluated_ideas.json").write_text(
        response.model_dump_json(indent=2),
        encoding="utf-8",
    )
    saved = archive_stage1(tmp_path, response.model_dump_json())

    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "Pain" in page.text
    assert "Founder fit" in page.text
    assert response.top_3_ideas[0].idea_title in page.text
    assert saved.name[:-5] in page.text

    approved = client.post("/approve", json={"idea_id": response.top_3_ideas[0].idea_id})
    assert approved.status_code == 200
    assert approved.json()["ok"] is True
    assert list((tmp_path / "prds").glob("*.md"))


def test_founder_form_updates_budget_and_skills(monkeypatch, tmp_path: Path):
    profile = tmp_path / "founder.yaml"
    profile.write_text(
        "\n".join(
            [
                "founder:",
                '  name: "Ada"',
                "  constraints:",
                "    max_initial_startup_cost_usd: 2500",
                "    weekly_time_commitment_hours: 20",
                "  skills:",
                "    technical:",
                '      - "Python"',
                "    product_and_business:",
                '      - "Writing"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FOUNDER_PROFILE_PATH", str(profile))
    client = TestClient(app)
    saved = client.post(
        "/founder",
        json={
            "name": "Ada Lovelace",
            "max_cost": 800,
            "weekly_hours": 12,
            "technical_skills": "Python\nFastAPI",
        },
    )
    assert saved.status_code == 200
    loaded = load_founder_profile(profile)
    assert loaded["founder"]["name"] == "Ada Lovelace"
    assert loaded["founder"]["constraints"]["max_initial_startup_cost_usd"] == 800
    assert loaded["founder"]["constraints"]["weekly_time_commitment_hours"] == 12
    assert loaded["founder"]["skills"]["technical"] == ["Python", "FastAPI"]
    assert loaded["founder"]["skills"]["product_and_business"] == ["Writing"]
    page = client.get("/founder")
    assert "Ada Lovelace" in page.text
    update_founder_profile(
        profile,
        name="Ada",
        max_cost=2500,
        weekly_hours=20,
        technical_skills=["Python"],
    )
