"""
Agent Skills Loader (agentskills.io specification)
Loads SKILL.md metadata, markdown instructions, and reference files from .agents/skills/
so that LangGraph nodes dynamically use the portable Agent Skills definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"
DEFAULT_FOUNDER_PROFILE = PROJECT_ROOT / "config" / "founder_profile.yaml"


@dataclass
class AgentSkill:
    name: str
    description: str
    instructions: str
    path: Path
    references: Dict[str, str] = field(default_factory=dict)


def parse_skill_md(skill_md_path: Path) -> AgentSkill:
    """Parse an agentskills.io SKILL.md file with YAML frontmatter and Markdown body."""
    raw = skill_md_path.read_text(encoding="utf-8")
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
    if frontmatter_match:
        meta_raw, body = frontmatter_match.group(1), frontmatter_match.group(2)
        meta = yaml.safe_load(meta_raw) or {}
    else:
        meta = {}
        body = raw

    skill_dir = skill_md_path.parent
    name = meta.get("name", skill_dir.name)
    description = meta.get("description", "")

    references: Dict[str, str] = {}
    refs_dir = skill_dir / "references"
    if refs_dir.exists() and refs_dir.is_dir():
        for ref_file in refs_dir.glob("*"):
            if ref_file.is_file():
                references[ref_file.name] = ref_file.read_text(encoding="utf-8")

    return AgentSkill(
        name=name,
        description=description.strip(),
        instructions=body.strip(),
        path=skill_md_path,
        references=references,
    )


def load_all_skills(skills_dir: Path = SKILLS_DIR) -> Dict[str, AgentSkill]:
    """Discover and load all SKILL.md packages in .agents/skills/."""
    skills: Dict[str, AgentSkill] = {}
    if not skills_dir.exists():
        return skills

    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        skill = parse_skill_md(skill_md)
        skills[skill.name] = skill
    return skills


def get_skill_prompt(skill_name: str, include_references: bool = True) -> str:
    """Return the complete system prompt for a named skill from .agents/skills/<skill_name>/SKILL.md."""
    skills = load_all_skills()
    if skill_name not in skills:
        raise KeyError(f"Skill '{skill_name}' not found in {SKILLS_DIR}. Available: {list(skills.keys())}")

    skill = skills[skill_name]
    parts: List[str] = [
        f"# Active Agent Skill: {skill.name}",
        f"**Role Description:** {skill.description}",
        "",
        skill.instructions,
    ]
    if include_references and skill.references:
        for ref_name, ref_content in skill.references.items():
            parts.append(f"\n---\n## Bundled Reference: {ref_name}\n\n{ref_content}")
    return "\n".join(parts)


def load_founder_profile(profile_path: Path | str | None = None) -> Dict[str, Any]:
    """Load the configurable Founder Profile YAML used by the Founder-Market Fit Agent."""
    target = Path(profile_path) if profile_path else DEFAULT_FOUNDER_PROFILE
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    if not target.exists():
        return {"founder": {"name": "Default Founder", "constraints": {"max_initial_startup_cost_usd": 2500}}}
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}
