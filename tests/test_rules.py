"""Tests for the rules engine: models, loader, matcher."""

import os
import tempfile
import pytest
import yaml

from aimv.rules.models import CategoryRule, NamingConvention
from aimv.rules.loader import (
    load_rules_from_file,
    load_default_rules,
    merge_rules,
    validate_rules,
)
from aimv.rules.matcher import match_file, build_rule_context_for_prompt, _score_rule


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class TestNamingConvention:
    def test_defaults(self):
        nc = NamingConvention()
        assert nc.template == "{description}.{ext}"
        assert nc.case == "preserve"

    def test_apply_case_title(self):
        nc = NamingConvention(case="title", separator="_")
        assert nc.apply_case("hello_world") == "Hello_World"

    def test_apply_case_lower(self):
        nc = NamingConvention(case="lower")
        assert nc.apply_case("HELLO") == "hello"

    def test_apply_case_upper(self):
        nc = NamingConvention(case="upper")
        assert nc.apply_case("hello") == "HELLO"

    def test_apply_case_preserve(self):
        nc = NamingConvention(case="preserve")
        assert nc.apply_case("HeLLo") == "HeLLo"

    def test_from_dict(self):
        nc = NamingConvention.from_dict({
            "template": "{date}_{name}.{ext}",
            "separator": "-",
            "case": "lower",
        })
        assert nc.template == "{date}_{name}.{ext}"
        assert nc.separator == "-"
        assert nc.case == "lower"

    def test_from_dict_empty(self):
        nc = NamingConvention.from_dict({})
        assert nc.template == "{description}.{ext}"

    def test_to_dict_roundtrip(self):
        nc = NamingConvention(template="{a}.{b}", date_format="%Y", separator="-", case="upper")
        d = nc.to_dict()
        nc2 = NamingConvention.from_dict(d)
        assert nc.template == nc2.template
        assert nc.case == nc2.case


class TestCategoryRule:
    def test_from_dict_minimal(self):
        rule = CategoryRule.from_dict({"name": "test"})
        assert rule.name == "test"
        assert rule.priority == 0
        assert rule.keywords == []

    def test_from_dict_full(self):
        data = {
            "name": "receipts",
            "description": "Purchase receipts",
            "priority": 10,
            "keywords": ["receipt", "purchase"],
            "filename_patterns": ["*receipt*"],
            "target_folder": "~/Documents/Receipts/",
            "naming": {"template": "{date}_{vendor}.{ext}", "case": "title"},
            "metadata_fields": ["date", "vendor"],
            "create_subfolders": True,
            "examples": [{"input": "a.pdf", "output": "b.pdf"}],
        }
        rule = CategoryRule.from_dict(data)
        assert rule.name == "receipts"
        assert rule.priority == 10
        assert rule.naming.case == "title"
        assert len(rule.examples) == 1

    def test_to_dict_roundtrip(self):
        rule = CategoryRule(name="test", priority=5, keywords=["a", "b"])
        d = rule.to_dict()
        rule2 = CategoryRule.from_dict(d)
        assert rule.name == rule2.name
        assert rule.priority == rule2.priority
        assert rule.keywords == rule2.keywords


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #

class TestLoader:
    def test_load_rules_from_file_single(self, tmp_path):
        rule_data = {"name": "test_rule", "priority": 5, "keywords": ["alpha"]}
        path = tmp_path / "test.yaml"
        path.write_text(yaml.dump(rule_data))
        rules = load_rules_from_file(str(path))
        assert len(rules) == 1
        assert rules[0].name == "test_rule"

    def test_load_rules_from_file_list(self, tmp_path):
        rule_data = [
            {"name": "r1", "priority": 1},
            {"name": "r2", "priority": 2},
        ]
        path = tmp_path / "multi.yaml"
        path.write_text(yaml.dump(rule_data))
        rules = load_rules_from_file(str(path))
        assert len(rules) == 2

    def test_load_rules_from_file_empty(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        rules = load_rules_from_file(str(path))
        assert rules == []

    def test_load_default_rules(self):
        rules = load_default_rules()
        assert len(rules) >= 7
        names = {r.name for r in rules}
        assert "receipts" in names
        assert "bank_statements" in names
        assert "general" in names

    def test_merge_rules_override(self):
        defaults = [CategoryRule(name="a", priority=1), CategoryRule(name="b", priority=2)]
        custom = [CategoryRule(name="a", priority=10, description="custom")]
        merged = merge_rules(defaults, custom)
        a_rule = next(r for r in merged if r.name == "a")
        assert a_rule.priority == 10
        assert a_rule.description == "custom"
        assert len(merged) == 2

    def test_merge_rules_new(self):
        defaults = [CategoryRule(name="a", priority=1)]
        custom = [CategoryRule(name="c", priority=5)]
        merged = merge_rules(defaults, custom)
        assert len(merged) == 2

    def test_merge_rules_sorted_by_priority(self):
        defaults = [CategoryRule(name="low", priority=1), CategoryRule(name="high", priority=10)]
        merged = merge_rules(defaults, [])
        assert merged[0].name == "high"

    def test_validate_rules_warnings(self):
        rules = [
            CategoryRule(name="no_match"),  # no keywords or patterns
            CategoryRule(name="no_target", keywords=["k"]),  # no target folder
        ]
        warnings = validate_rules(rules)
        assert any("never match" in w for w in warnings)
        assert any("no target_folder" in w for w in warnings)

    def test_validate_rules_duplicate(self):
        rules = [CategoryRule(name="dup", keywords=["x"]), CategoryRule(name="dup", keywords=["y"])]
        warnings = validate_rules(rules)
        assert any("Duplicate" in w for w in warnings)


# --------------------------------------------------------------------------- #
# Matcher
# --------------------------------------------------------------------------- #

class TestMatcher:
    def _make_rule(self, name, keywords=None, patterns=None, priority=5):
        return CategoryRule(
            name=name,
            priority=priority,
            keywords=keywords or [],
            filename_patterns=patterns or [],
            target_folder=f"~/{name}/",
            naming=NamingConvention(template="{description}.{ext}"),
        )

    def test_match_by_keywords(self):
        rules = [self._make_rule("receipts", keywords=["receipt", "purchase"])]
        result = match_file("/tmp/doc.pdf", "This is a purchase receipt from Nike", rules)
        assert result is not None
        assert result.name == "receipts"

    def test_match_by_filename_pattern(self):
        rules = [self._make_rule("photos", patterns=["*IMG_*"])]
        result = match_file("/tmp/IMG_20250101.jpg", "", rules)
        assert result is not None
        assert result.name == "photos"

    def test_no_match_returns_general(self):
        general = CategoryRule(name="general", priority=0)
        rules = [
            self._make_rule("receipts", keywords=["receipt"]),
            general,
        ]
        result = match_file("/tmp/random.txt", "Just some random text", rules)
        assert result is not None
        assert result.name == "general"

    def test_no_match_no_general_returns_none(self):
        rules = [self._make_rule("receipts", keywords=["receipt"])]
        result = match_file("/tmp/random.txt", "Nothing relevant", rules)
        assert result is None

    def test_highest_score_wins(self):
        rules = [
            self._make_rule("receipts", keywords=["receipt", "purchase", "order"]),
            self._make_rule("invoices", keywords=["invoice"]),
        ]
        result = match_file("/tmp/doc.pdf", "Purchase receipt for order", rules)
        assert result.name == "receipts"

    def test_score_function(self):
        rule = self._make_rule("test", keywords=["alpha", "beta"], patterns=["*test*"])
        score = _score_rule("/tmp/test_file.pdf", "This has alpha content", rule)
        assert 0.0 < score <= 1.0

    def test_build_rule_context(self):
        rule = CategoryRule(
            name="receipts",
            description="Purchase receipts",
            target_folder="~/Docs/Receipts/{year}/",
            naming=NamingConvention(template="{date}_{vendor}.{ext}", case="title"),
            metadata_fields=["date", "vendor"],
            create_subfolders=True,
            examples=[{"input": "a.pdf", "output": "b.pdf", "reasoning": "test"}],
        )
        ctx = build_rule_context_for_prompt(rule)
        assert "receipts" in ctx
        assert "Receipts/{year}/" in ctx
        assert "{date}_{vendor}.{ext}" in ctx
        assert "date, vendor" in ctx
        assert "a.pdf" in ctx
