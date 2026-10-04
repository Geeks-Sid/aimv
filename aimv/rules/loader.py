"""Load, merge, and validate YAML rule files."""

import os
import glob
from typing import List, Optional

import yaml

from aimv.rules.models import CategoryRule


def load_rules_from_file(path: str) -> List[CategoryRule]:
    """Parse a single YAML rule file into CategoryRule objects.

    A YAML file may contain a single rule dict or a list of rule dicts.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return []

    if isinstance(data, dict):
        return [CategoryRule.from_dict(data)]
    elif isinstance(data, list):
        return [CategoryRule.from_dict(item) for item in data if isinstance(item, dict)]

    return []


def load_default_rules() -> List[CategoryRule]:
    """Load all built-in YAML rule files shipped with aimv."""
    defaults_dir = os.path.join(os.path.dirname(__file__), "defaults")
    if not os.path.isdir(defaults_dir):
        return []

    rules: List[CategoryRule] = []
    for yaml_path in sorted(glob.glob(os.path.join(defaults_dir, "*.yaml"))):
        try:
            rules.extend(load_rules_from_file(yaml_path))
        except Exception as e:
            print(f"Warning: Failed to load default rule {yaml_path}: {e}")
    return rules


def load_user_rules(user_rules_dir: str) -> List[CategoryRule]:
    """Load user-defined rule files from ~/.aimv/rules/."""
    if not os.path.isdir(user_rules_dir):
        return []

    rules: List[CategoryRule] = []
    for yaml_path in sorted(glob.glob(os.path.join(user_rules_dir, "*.yaml"))):
        try:
            rules.extend(load_rules_from_file(yaml_path))
        except Exception as e:
            print(f"Warning: Failed to load user rule {yaml_path}: {e}")
    return rules


def merge_rules(
    defaults: List[CategoryRule], custom: List[CategoryRule]
) -> List[CategoryRule]:
    """Merge user rules over defaults. Same name = override, new name = append.

    Result is sorted by priority descending (highest first).
    """
    rule_map = {r.name: r for r in defaults}
    for r in custom:
        rule_map[r.name] = r
    return sorted(rule_map.values(), key=lambda r: r.priority, reverse=True)


def validate_rules(rules: List[CategoryRule]) -> List[str]:
    """Return a list of validation warnings for a set of rules."""
    warnings: List[str] = []
    seen_names: set = set()

    for rule in rules:
        if not rule.name:
            warnings.append("Rule found with empty name")
            continue

        if rule.name in seen_names:
            warnings.append(f"Duplicate rule name: '{rule.name}'")
        seen_names.add(rule.name)

        if not rule.keywords and not rule.filename_patterns:
            warnings.append(
                f"Rule '{rule.name}': no keywords or filename_patterns defined — "
                "this rule will never match"
            )

        if not rule.target_folder:
            warnings.append(f"Rule '{rule.name}': no target_folder defined")

        if not rule.naming.template:
            warnings.append(f"Rule '{rule.name}': naming template is empty")

    return warnings


def load_all_rules(user_rules_dir: Optional[str] = None) -> List[CategoryRule]:
    """Load and merge default + user rules, returning the final rule set."""
    defaults = load_default_rules()

    custom: List[CategoryRule] = []
    if user_rules_dir:
        custom = load_user_rules(user_rules_dir)

    merged = merge_rules(defaults, custom)

    warnings = validate_rules(merged)
    for w in warnings:
        print(f"Rule validation: {w}")

    return merged
