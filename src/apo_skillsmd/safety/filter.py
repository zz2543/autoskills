"""Safety filter that applies hard constraints before execution."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from apo_skillsmd.safety.regex_rules import scan_text
from apo_skillsmd.safety.static_bandit import run_bandit_scan
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import SafetyAction, SafetySeverity


class SafetyFinding(BaseModel):
    """One safety issue detected during static scanning."""

    source: str
    rule_id: str
    category: str
    severity: SafetySeverity
    action: SafetyAction
    message: str


class SafetyVerdict(BaseModel):
    """Policy decision for a skill candidate."""

    action: SafetyAction = SafetyAction.ALLOW
    findings: list[SafetyFinding] = Field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.action == SafetyAction.ALLOW


class SafetyFilter:
    """Static safety scanner used by initialization, mutation, and crossover."""

    def scan(self, skill_or_path: Skill | str | Path) -> SafetyVerdict:
        skill = load_skill(skill_or_path) if isinstance(skill_or_path, (str, Path)) else skill_or_path
        findings: list[SafetyFinding] = []

        blobs = {"SKILL.md": skill.md_body}
        blobs.update({path: script.content for path, script in skill.scripts.items()})

        for source, content in blobs.items():
            for rule in scan_text(content):
                findings.append(
                    SafetyFinding(
                        source=source,
                        rule_id=rule.rule_id,
                        category=rule.category,
                        severity=rule.severity,
                        action=rule.action,
                        message=rule.description,
                    )
                )

        if skill.path:
            for issue in run_bandit_scan(skill.path):
                findings.append(
                    SafetyFinding(
                        source=issue.get("filename", "bandit"),
                        rule_id=issue.get("test_id", "bandit"),
                        category=issue.get("test_name", "bandit"),
                        severity=SafetySeverity(issue.get("issue_severity", "LOW").lower()),
                        action=SafetyAction.HARD_REJECT,
                        message=issue.get("issue_text", "Bandit finding"),
                    )
                )

        action = SafetyAction.ALLOW
        if any(finding.action == SafetyAction.HARD_REJECT for finding in findings):
            action = SafetyAction.HARD_REJECT
        elif any(finding.action == SafetyAction.SOFT_REJECT for finding in findings):
            action = SafetyAction.SOFT_REJECT
        return SafetyVerdict(action=action, findings=findings)
