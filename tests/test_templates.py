"""Tests for the organization template system."""

import os
import pytest
import yaml

from aimv.templates.org_template import OrgTemplate


class TestOrgTemplate:
    @pytest.fixture
    def template(self, tmp_path):
        return OrgTemplate(str(tmp_path / "template.yaml"))

    @pytest.fixture
    def sample_dirs(self, tmp_path):
        """Create a sample directory tree for scanning."""
        base = tmp_path / "home"
        (base / "Documents" / "Financial" / "Receipts").mkdir(parents=True)
        (base / "Documents" / "Financial" / "Bank").mkdir(parents=True)
        (base / "Documents" / "School" / "Physics").mkdir(parents=True)
        (base / "Pictures" / "Vacations").mkdir(parents=True)
        (base / "Pictures" / "Family").mkdir(parents=True)
        (base / "Downloads").mkdir(parents=True)
        # Hidden dir that should be excluded
        (base / "Documents" / ".hidden_dir").mkdir(parents=True)
        return base

    def test_generate(self, template, sample_dirs):
        roots = [
            str(sample_dirs / "Documents"),
            str(sample_dirs / "Pictures"),
        ]
        result = template.generate(roots, max_depth=3)
        assert "roots" in result
        assert "generated_at" in result
        assert len(result["roots"]) == 2

    def test_generate_skips_hidden(self, template, sample_dirs):
        result = template.generate(
            [str(sample_dirs / "Documents")], max_depth=3
        )
        root_key = str(sample_dirs / "Documents")
        tree = result["roots"][root_key]
        assert ".hidden_dir" not in tree.get("Financial", {})
        assert ".hidden_dir" not in tree

    def test_generate_nonexistent_dir(self, template, tmp_path):
        result = template.generate([str(tmp_path / "nonexistent")], max_depth=2)
        assert result["roots"] == {}

    def test_generate_respects_max_depth(self, template, sample_dirs):
        result = template.generate(
            [str(sample_dirs / "Documents")], max_depth=1
        )
        root_key = str(sample_dirs / "Documents")
        tree = result["roots"][root_key]
        # At depth 1, we see the immediate children but not their children
        assert "Financial" in tree
        assert tree["Financial"] == {}  # max_depth=1 means no deeper scanning

    def test_save_and_load(self, template, sample_dirs):
        template.generate(
            [str(sample_dirs / "Documents")], max_depth=2
        )
        template.save()
        assert os.path.exists(template.template_path)

        template2 = OrgTemplate(template.template_path)
        loaded = template2.load()
        assert "roots" in loaded
        assert "generated_at" in loaded

    def test_build_prompt_context(self, template, sample_dirs):
        template.generate(
            [str(sample_dirs / "Documents"), str(sample_dirs / "Pictures")],
            max_depth=3,
        )
        ctx = template.build_prompt_context()
        assert "Current folder organization:" in ctx
        assert "Financial/" in ctx
        assert "Receipts/" in ctx
        assert "School/" in ctx

    def test_build_prompt_context_empty(self, template):
        ctx = template.build_prompt_context()
        assert ctx == ""

    def test_get_locations_for_category(self, template, sample_dirs):
        template.generate(
            [str(sample_dirs / "Documents"), str(sample_dirs / "Pictures")],
            max_depth=3,
        )
        locations = template.get_locations_for_category("receipts")
        assert len(locations) >= 1
        assert any("Receipts" in loc for loc in locations)

    def test_get_locations_for_category_no_match(self, template, sample_dirs):
        template.generate([str(sample_dirs / "Documents")], max_depth=3)
        locations = template.get_locations_for_category("zzz_nonexistent")
        assert locations == []

    def test_save_creates_parent_dirs(self, tmp_path):
        deep_path = str(tmp_path / "a" / "b" / "template.yaml")
        template = OrgTemplate(deep_path)
        template.generate([], max_depth=1)
        template.save()
        assert os.path.exists(deep_path)

    def test_load_nonexistent(self, template):
        result = template.load()
        assert result == {}

    def test_yaml_format(self, template, sample_dirs):
        template.generate([str(sample_dirs / "Documents")], max_depth=2)
        template.save()

        with open(template.template_path, "r") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "roots" in data
