"""Match files to rules and build LLM prompt context from matched rules."""

import fnmatch
import os
from typing import List, Optional

from aimv.rules.models import CategoryRule


MATCH_THRESHOLD = 0.10


def _score_rule(
    file_path: str, file_summary: str, rule: CategoryRule
) -> float:
    """Score how well a rule matches a file based on filename patterns and keywords.

    Returns a float between 0.0 and 1.0.
    """
    if not rule.keywords and not rule.filename_patterns:
        return 0.0

    filename = os.path.basename(file_path).lower()
    summary_lower = file_summary.lower() if file_summary else ""
    combined_text = f"{filename} {summary_lower}"

    score = 0.0
    max_possible = 0.0

    # Filename pattern matching (weight: 0.4)
    if rule.filename_patterns:
        pattern_matches = sum(
            1 for pattern in rule.filename_patterns
            if fnmatch.fnmatch(filename, pattern.lower())
        )
        pattern_score = pattern_matches / len(rule.filename_patterns)
        score += 0.4 * pattern_score
        max_possible += 0.4

    # Keyword matching in summary + filename (weight: 0.6)
    if rule.keywords:
        keyword_matches = sum(
            1 for kw in rule.keywords if kw.lower() in combined_text
        )
        keyword_score = keyword_matches / len(rule.keywords)
        score += 0.6 * keyword_score
        max_possible += 0.6

    if max_possible == 0:
        return 0.0

    return score / max_possible


def match_file(
    file_path: str,
    file_summary: str,
    rules: List[CategoryRule],
) -> Optional[CategoryRule]:
    """Find the best matching rule for a file.

    Scores each rule, returns the highest-scoring rule above the threshold.
    The general catch-all rule (priority 0, no keywords) is only returned
    if no other rule matches.
    """
    if not rules:
        return None

    scored = []
    general_rule = None

    for rule in rules:
        if not rule.keywords and not rule.filename_patterns:
            general_rule = rule
            continue
        score = _score_rule(file_path, file_summary, rule)
        if score >= MATCH_THRESHOLD:
            scored.append((score, rule))

    if scored:
        scored.sort(key=lambda x: (-x[0], -x[1].priority))
        return scored[0][1]

    return general_rule


def build_rule_context_for_prompt(rule: CategoryRule) -> str:
    """Convert a matched rule into structured text for LLM prompt injection.

    This text block tells the LLM what organizational rules to follow for this
    category of file, including naming conventions, target folders, and examples.
    """
    lines = [
        "FILE ORGANIZATION RULE (follow these guidelines for this file):",
        f"  Category: {rule.name}",
        f"  Description: {rule.description}",
        f"  Preferred target folder: {rule.target_folder}",
        f"  Naming convention: {rule.naming.template}",
        f"    Date format: {rule.naming.date_format}",
        f"    Separator: '{rule.naming.separator}'",
        f"    Case style: {rule.naming.case}",
    ]

    if rule.metadata_fields:
        lines.append(
            f"  Metadata to extract from content: {', '.join(rule.metadata_fields)}"
        )

    if rule.create_subfolders:
        lines.append(
            "  Auto-create subfolders: Yes (organize into year/month or similar hierarchy)"
        )

    if rule.examples:
        lines.append("  Naming examples:")
        for ex in rule.examples:
            lines.append(f"    Input:  {ex.get('input', '?')}")
            lines.append(f"    Output: {ex.get('output', '?')}")
            if ex.get("reasoning"):
                lines.append(f"    Why:    {ex['reasoning']}")

    lines.append("---")
    return "\n".join(lines)
