"""Regex-based hard and soft safety rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

from apo_skillsmd.types import SafetyAction, SafetySeverity


@dataclass(frozen=True)
class RegexRule:
    """One static safety rule."""

    rule_id: str
    category: str
    pattern: str
    severity: SafetySeverity
    action: SafetyAction
    description: str


REGEX_RULES: list[RegexRule] = [
    RegexRule(
        rule_id="hard-eval-exec",
        category="arbitrary_code_execution",
        pattern=r"\b(eval|exec|compile|__import__)\s*\(",
        severity=SafetySeverity.HIGH,
        action=SafetyAction.HARD_REJECT,
        description="Reject arbitrary code execution helpers.",
    ),
    RegexRule(
        rule_id="hard-shell-true",
        category="shell_injection",
        pattern=r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True",
        severity=SafetySeverity.HIGH,
        action=SafetyAction.HARD_REJECT,
        description="Reject shell=True subprocess usage.",
    ),
    RegexRule(
        rule_id="hard-network",
        category="network_access",
        pattern=r"\b(requests|urllib|socket)\b",
        severity=SafetySeverity.HIGH,
        action=SafetyAction.HARD_REJECT,
        description="Reject non-whitelisted network libraries.",
    ),
    RegexRule(
        rule_id="hard-sandbox-escape",
        category="sandbox_escape",
        pattern=r"(/proc/|/sys/|ptrace|ctypes)",
        severity=SafetySeverity.HIGH,
        action=SafetyAction.HARD_REJECT,
        description="Reject common sandbox escape primitives.",
    ),
    RegexRule(
        rule_id="hard-prompt-injection",
        category="prompt_injection",
        pattern=r"ignore\s+previous\s+instructions|system\s+prompt",
        severity=SafetySeverity.MEDIUM,
        action=SafetyAction.HARD_REJECT,
        description="Reject direct prompt injection strings in SKILL.md.",
    ),
]


def scan_text(text: str) -> list[RegexRule]:
    """Return all rules matched by the input text."""

    matches: list[RegexRule] = []
    for rule in REGEX_RULES:
        if re.search(rule.pattern, text, flags=re.IGNORECASE | re.MULTILINE):
            matches.append(rule)
    return matches
