"""Local results page: top ideas, score breakdown, approval, and founder settings."""

from __future__ import annotations

import html
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models import EvaluatedStartupIdea, Stage2PRDRequest
from src.skill_loader import PROJECT_ROOT, load_founder_profile

SCORE_PARTS = (
    ("pain_severity_score", "Pain", "25%"),
    ("low_startup_cost_score", "Startup cost", "25%"),
    ("competition_gap_score", "Competition", "20%"),
    ("tam_sweet_spot_score", "Market size", "15%"),
    ("founder_fit_score", "Founder fit", "15%"),
)


def output_dir() -> Path:
    raw = os.getenv("OUTPUT_DIR", "").strip()
    directory = Path(raw) if raw else PROJECT_ROOT / "outputs"
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    return directory


def founder_profile_path() -> Path:
    raw = os.getenv("FOUNDER_PROFILE_PATH", "").strip()
    target = Path(raw) if raw else PROJECT_ROOT / "config" / "founder_profile.yaml"
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    return target


def archive_stage1(directory: Path, payload: str) -> Path:
    """Keep a dated copy so a later run does not erase this one."""
    runs = directory / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = runs / f"{stamp}.json"
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = runs / f"{stamp}.json"
    path.write_text(payload, encoding="utf-8")
    return path


def list_runs(directory: Path) -> list[Path]:
    runs = directory / "runs"
    if not runs.exists():
        return []
    return sorted(runs.glob("*.json"), reverse=True)


def _safe_run_name(name: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.json", name or ""):
        return None
    return name


def load_run(directory: Path, run_name: str | None = None) -> dict[str, Any] | None:
    if run_name:
        safe = _safe_run_name(run_name)
        path = directory / "runs" / safe if safe else None
    else:
        path = directory / "stage1_evaluated_ideas.json"
    if path is None or not path.is_file():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def prd_path(directory: Path, idea_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", idea_id).strip("-")[:80] or "idea"
    return directory / "prds" / f"{safe}.md"


def stage2_request_from_idea(idea: EvaluatedStartupIdea) -> Stage2PRDRequest:
    return Stage2PRDRequest(
        idea_id=idea.idea_id,
        idea_title=idea.idea_title,
        one_line_pitch=idea.one_line_pitch,
        core_problem=idea.core_problem,
        target_customer=idea.target_customer,
        source_subreddit=idea.source_subreddit,
        source_reddit_title=idea.source_reddit_title,
        source_reddit_url=idea.source_reddit_url,
        bottom_up_tam_summary=idea.research.tam.tam_formula_explanation,
        startup_cost_summary=idea.research.startup_cost_breakdown,
        competitors_summary=", ".join(f"{c.name} ({c.pricing})" for c in idea.research.competitors),
        competitive_wedge=idea.research.competitive_wedge,
        founder_fit_summary=idea.founder_fit.fit_rationale,
        total_score=idea.scores.weighted_total_score,
        founder_fit_score=idea.founder_fit.founder_fit_score,
        founder_fit_verdict=idea.founder_fit.fit_verdict,
        target_buyer_count=idea.research.tam.estimated_target_users,
        annual_price_usd=idea.research.tam.annual_price_usd,
        bottom_up_tam_usd=idea.research.tam.bottom_up_tam_usd,
        customers_for_10k_mrr=idea.research.tam.customers_for_10k_mrr,
        startup_cost_usd=idea.research.estimated_startup_cost_usd,
    )


def find_idea(payload: dict[str, Any], idea_id: str) -> EvaluatedStartupIdea | None:
    for raw in payload.get("all_evaluated_ideas") or payload.get("top_3_ideas") or []:
        if raw.get("idea_id") == idea_id:
            return EvaluatedStartupIdea.model_validate(raw)
    return None


def update_founder_profile(
    path: Path,
    *,
    name: str,
    max_cost: int,
    weekly_hours: int,
    technical_skills: list[str],
) -> None:
    """Update the founder fields the form edits and leave the rest of the file in place."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text.strip():
        text = "founder:\n  name: \"Founder\"\n  constraints:\n    max_initial_startup_cost_usd: 2500\n    weekly_time_commitment_hours: 20\n  skills:\n    technical: []\n"
    text = re.sub(r"(?m)^(\s*name:\s*).*$", lambda m: f'{m.group(1)}"{_yaml_quote(name)}"', text, count=1)
    text = re.sub(
        r"(?m)^(\s*max_initial_startup_cost_usd:\s*)\d+",
        lambda m: f"{m.group(1)}{int(max_cost)}",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(\s*weekly_time_commitment_hours:\s*)\d+",
        lambda m: f"{m.group(1)}{int(weekly_hours)}",
        text,
        count=1,
    )
    text = _replace_technical_skills(text, technical_skills)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _yaml_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _replace_technical_skills(text: str, skills: list[str]) -> str:
    lines = text.splitlines()
    start = None
    indent = ""
    for index, line in enumerate(lines):
        if re.match(r"^\s*technical:\s*$", line):
            start = index
            indent = re.match(r"^(\s*)", line).group(1) + "  "
            break
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].lstrip().startswith("-")):
        end += 1
    items = [f'{indent}- "{_yaml_quote(skill)}"' for skill in skills if skill.strip()]
    return "\n".join(lines[: start + 1] + items + lines[end:]) + ("\n" if text.endswith("\n") else "")


def founder_form_values(path: Path | None = None) -> dict[str, Any]:
    profile = load_founder_profile(path)
    founder = profile.get("founder") or {}
    constraints = founder.get("constraints") or {}
    technical = ((founder.get("skills") or {}).get("technical")) or []
    return {
        "name": founder.get("name") or "",
        "max_cost": constraints.get("max_initial_startup_cost_usd") or 2500,
        "weekly_hours": constraints.get("weekly_time_commitment_hours") or 20,
        "technical_skills": "\n".join(str(item) for item in technical),
    }


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _amount(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _score_rows(scores: dict[str, Any]) -> str:
    rows = []
    for key, label, weight in SCORE_PARTS:
        raw = scores.get(key) or 0
        try:
            number = float(raw)
        except (TypeError, ValueError):
            number = 0
        width = max(0, min(100, number * 10))
        rows.append(
            "<div class='part'>"
            f"<div class='part-label'><span>{_esc(label)}</span><span>{_esc(weight)} · {_esc(number)}</span></div>"
            f"<div class='track'><div class='fill' style='width:{width:.0f}%'></div></div>"
            "</div>"
        )
    return "".join(rows)


def is_live_article_url(url: str) -> bool:
    """Fixture posts use made-up Reddit slugs. Live Hacker News ids do not."""
    if not url.startswith(("http://", "https://")):
        return False
    marker = "/comments/"
    if "reddit.com" in url and marker in url:
        slug = url.split(marker, 1)[1].split("/", 1)[0]
        if "_" in slug or not re.fullmatch(r"[a-z0-9]+", slug):
            return False
    return True


def source_html(idea: dict[str, Any]) -> str:
    url = idea.get("source_reddit_url") or ""
    title = idea.get("source_reddit_title") or url
    discussion = idea.get("discussion_url") or ""
    if not is_live_article_url(url):
        return f"{_esc(title)} <span class='meta'>(sample post, not a live article)</span>"
    links = [f"<a href='{_esc(url)}' target='_blank' rel='noopener'>{_esc(title)}</a>"]
    if is_live_article_url(discussion) and discussion.rstrip("/") != url.rstrip("/"):
        links.append(
            f"<a href='{_esc(discussion)}' target='_blank' rel='noopener'>Hacker News thread</a>"
        )
    return " · ".join(links)


def save_stage1(directory: Path, payload: str, rows: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "stage1_evaluated_ideas.json").write_text(payload, encoding="utf-8")
    archive_stage1(directory, payload)
    if not rows:
        return
    import csv

    csv_path = directory / "google_sheets_evaluated_ideas.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _idea_card(idea: dict[str, Any], plan: str | None, run_name: str) -> str:
    scores = idea.get("scores") or {}
    research = idea.get("research") or {}
    tam = research.get("tam") or {}
    fit = idea.get("founder_fit") or {}
    total = scores.get("weighted_total_score", "n/a")
    source = source_html(idea)
    plan_html = ""
    if plan:
        plan_html = f"<details open><summary>Product plan</summary><pre>{_esc(plan)}</pre></details>"
    run_field = f"<input type='hidden' name='run' value='{_esc(run_name)}'>" if run_name else ""
    return f"""
    <article class="card">
      <header>
        <p class="rank">#{_esc(idea.get("rank"))} · {_esc(fit.get("fit_verdict") or "")}</p>
        <h2>{_esc(idea.get("idea_title"))}</h2>
        <p class="pitch">{_esc(idea.get("one_line_pitch"))}</p>
      </header>
      <p class="total">{_esc(total)}<span>/100</span></p>
      {_score_rows(scores)}
      <dl>
        <div><dt>Customer</dt><dd>{_esc(idea.get("target_customer"))}</dd></div>
        <div><dt>Startup cost</dt><dd>${_amount(research.get("estimated_startup_cost_usd"))}</dd></div>
        <div><dt>Market</dt><dd>${_amount(tam.get("bottom_up_tam_usd"))}/yr</dd></div>
        <div><dt>Price</dt><dd>${_amount(tam.get("monthly_price_usd"))}/mo</dd></div>
        <div><dt>Source</dt><dd>{source}</dd></div>
      </dl>
      <p class="why">{_esc(idea.get("evaluator_verdict"))}</p>
      <form class="approve" data-idea="{_esc(idea.get("idea_id"))}">
        {run_field}
        <button type="submit">Write the plan for this idea</button>
        <p class="status" hidden>Writing the plan. This can take a few minutes.</p>
      </form>
      {plan_html}
    </article>
    """


def render_board(payload: dict[str, Any] | None, *, run_name: str = "", runs: list[str] | None = None, notice: str = "") -> str:
    ideas = []
    if payload:
        ideas = payload.get("top_3_ideas") or []
    directory = output_dir()
    cards = []
    for idea in ideas:
        path = prd_path(directory, idea.get("idea_id") or "")
        # prd_path creates the folder; don't leave an empty requirement
        plan = path.read_text(encoding="utf-8") if path.is_file() and path.stat().st_size else None
        cards.append(_idea_card(idea, plan, run_name))
    if not cards:
        body = "<p class='empty'>No scored ideas yet. In the project folder run <code>python cli.py --source curated</code>, then refresh this page.</p>"
    else:
        source = _esc((payload or {}).get("source_used") or "")
        mode = _esc((payload or {}).get("agent_mode") or "")
        body = f"<p class='meta'>Source {source} · model mode {mode}</p>" + "".join(cards)
    history = "".join(
        f"<li><a href='/?run={_esc(name)}'>{_esc(name[:-5])}</a></li>" for name in (runs or [])
    )
    notice_html = f"<p class='notice'>{_esc(notice)}</p>" if notice else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Startup Scout</title>
  <style>
    :root {{ color-scheme: light; --ink: #1c1915; --paper: #f6f1e7; --card: #fffdf8; --line: #e4d8c4; --fill: #c4552a; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font: 16px/1.5 "Segoe UI", sans-serif; color: var(--ink); background: var(--paper); }}
    header.top, main {{ width: min(980px, calc(100% - 32px)); margin: 0 auto; }}
    header.top {{ display: flex; justify-content: space-between; gap: 16px; align-items: end; padding: 28px 0 8px; }}
    h1 {{ font-family: Georgia, serif; font-weight: 500; margin: 0; }}
    a {{ color: var(--fill); }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 20px; margin: 16px 0; }}
    .rank, .meta, .status {{ color: #6d645b; }}
    h2 {{ margin: 0 0 8px; font-family: Georgia, serif; font-weight: 500; }}
    .pitch {{ margin-top: 0; }}
    .total {{ font: 500 42px Georgia, serif; margin: 8px 0; }}
    .total span {{ font-size: 18px; color: #6d645b; }}
    .part {{ margin: 8px 0; }}
    .part-label {{ display: flex; justify-content: space-between; font-size: 14px; }}
    .track {{ height: 8px; background: #efe6d8; border-radius: 99px; }}
    .fill {{ height: 8px; background: var(--fill); border-radius: 99px; }}
    dl {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }}
    dt {{ font-size: 12px; letter-spacing: .04em; text-transform: uppercase; color: #6d645b; }}
    dd {{ margin: 0; }}
    button {{ background: var(--ink); color: white; border: 0; border-radius: 999px; padding: 10px 16px; cursor: pointer; }}
    pre {{ white-space: pre-wrap; background: #f6f1e7; padding: 12px; border-radius: 12px; }}
    .history {{ font-size: 14px; }}
    .notice {{ background: #fff4d6; border: 1px solid #e4d8c4; padding: 10px 12px; border-radius: 12px; }}
  </style>
</head>
<body>
  <header class="top">
    <div>
      <h1>Startup Scout</h1>
      <p>Top ideas from the latest run, with the five scores behind each total.</p>
    </div>
    <p><button id="fetch-hn" type="button">Fetch 2 Hacker News posts</button> <a href="/founder">Founder profile</a></p>
  </header>
  <main>
    {notice_html}
    {body}
    <section class="history">
      <h2>Earlier runs</h2>
      <ul>{history or "<li>None saved yet. The next command-line run will keep a copy.</li>"}</ul>
    </section>
  </main>
  <script>
    document.getElementById("fetch-hn").addEventListener("click", async (event) => {{
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = "Fetching two Hacker News posts…";
      const response = await fetch("/fetch-hn", {{ method: "POST" }});
      if (!response.ok) {{
        button.disabled = false;
        button.textContent = "Fetch failed. Try again.";
        return;
      }}
      location.href = "/";
    }});
    document.querySelectorAll("form.approve").forEach((form) => {{
      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const status = form.querySelector(".status");
        status.hidden = false;
        form.querySelector("button").disabled = true;
        const response = await fetch("/approve", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ idea_id: form.dataset.idea, run: new URLSearchParams(location.search).get("run") || "" }})
        }});
        if (!response.ok) {{
          status.textContent = "The plan was not written. Check the API terminal.";
          form.querySelector("button").disabled = false;
          return;
        }}
        location.reload();
      }});
    }});
  </script>
</body>
</html>"""


def render_founder_form(values: dict[str, Any], notice: str = "") -> str:
    notice_html = f"<p class='notice'>{_esc(notice)}</p>" if notice else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Founder profile</title>
  <style>
    body {{ margin: 0; font: 16px/1.5 "Segoe UI", sans-serif; background: #f6f1e7; color: #1c1915; }}
    main {{ width: min(640px, calc(100% - 32px)); margin: 28px auto; }}
    label {{ display: block; margin: 14px 0; }}
    input, textarea {{ width: 100%; padding: 8px; border: 1px solid #e4d8c4; border-radius: 8px; }}
    button {{ background: #1c1915; color: white; border: 0; border-radius: 999px; padding: 10px 16px; }}
    a {{ color: #c4552a; }}
  </style>
</head>
<body>
  <main>
    <p><a href="/">Back to ideas</a></p>
    <h1>Founder profile</h1>
    <p>These limits are what the score uses. The next run picks them up. This page does not rescore old ideas.</p>
    {notice_html}
    <form id="founder">
      <label>Name <input name="name" value="{_esc(values.get("name"))}"></label>
      <label>Max startup cost in USD <input name="max_cost" type="number" min="0" value="{_esc(values.get("max_cost"))}"></label>
      <label>Hours per week <input name="weekly_hours" type="number" min="1" max="80" value="{_esc(values.get("weekly_hours"))}"></label>
      <label>Technical skills, one per line <textarea name="technical_skills" rows="6">{_esc(values.get("technical_skills"))}</textarea></label>
      <button type="submit">Save profile</button>
      <p class="status" hidden>Saved. The next pipeline run uses this profile.</p>
    </form>
  </main>
  <script>
    document.getElementById("founder").addEventListener("submit", async (event) => {{
      event.preventDefault();
      const form = event.currentTarget;
      const data = Object.fromEntries(new FormData(form).entries());
      const response = await fetch("/founder", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(data)
      }});
      const status = form.querySelector(".status");
      status.hidden = false;
      status.textContent = response.ok ? "Saved. The next pipeline run uses this profile." : "Could not save the profile.";
    }});
  </script>
</body>
</html>"""
