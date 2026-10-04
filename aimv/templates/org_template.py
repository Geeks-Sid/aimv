"""Organization template — scans and snapshots the user's folder structure for LLM context."""

import os
from typing import Any, Dict, List, Optional, Set

import yaml


class OrgTemplate:
    """Manages the user's organization template — a snapshot of their folder hierarchy."""

    DEFAULT_EXCLUDED = {
        ".", ".git", ".svn", ".hg", "__pycache__", "node_modules",
        ".Trash", ".Spotlight-V100", ".fseventsd", ".DS_Store",
        "venv", ".venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
        "$RECYCLE.BIN", "System Volume Information",
    }

    def __init__(self, template_path: str):
        self.template_path = template_path
        self._template: Optional[dict] = None

    def generate(
        self,
        root_dirs: List[str],
        max_depth: int = 3,
        excluded: Optional[Set[str]] = None,
    ) -> dict:
        """Walk filesystem and build a directory-only tree structure.

        Returns a dict like:
        {
            "generated_at": "...",
            "roots": {
                "~/Documents": {"Financial": {"Receipts": {}, "Bank": {}}, "School": {}},
                "~/Pictures": {"Vacations": {}, "Family": {}}
            }
        }
        """
        from datetime import datetime, timezone

        exclude_set = excluded or self.DEFAULT_EXCLUDED
        roots: Dict[str, Any] = {}

        for root_dir in root_dirs:
            expanded = os.path.expanduser(root_dir)
            if not os.path.isdir(expanded):
                continue
            tree = self._scan_dir(expanded, max_depth, 0, exclude_set)
            display_path = root_dir if root_dir.startswith("~") else expanded
            roots[display_path] = tree

        self._template = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "roots": roots,
        }
        return self._template

    def _scan_dir(
        self,
        path: str,
        max_depth: int,
        current_depth: int,
        excluded: Set[str],
    ) -> dict:
        """Recursively scan a directory, returning nested dicts of subdirectories."""
        if current_depth >= max_depth:
            return {}

        tree: Dict[str, Any] = {}
        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            return {}

        for entry in entries:
            if entry in excluded or entry.startswith("."):
                continue
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                tree[entry] = self._scan_dir(
                    full_path, max_depth, current_depth + 1, excluded
                )

        return tree

    def load(self) -> dict:
        """Load a saved template from YAML."""
        if not os.path.exists(self.template_path):
            return {}
        with open(self.template_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._template = data or {}
        return self._template

    def save(self, template: Optional[dict] = None) -> None:
        """Save the template to YAML."""
        data = template or self._template
        if data is None:
            return
        os.makedirs(os.path.dirname(self.template_path), exist_ok=True)
        with open(self.template_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        self._template = data

    def build_prompt_context(self) -> str:
        """Convert the template into a compact text for LLM prompt injection.

        Example output:
            Current folder organization:
              ~/Documents/
                Financial/
                  Receipts/
                  Bank_Statements/
                School/
                  2025 Spring/
              ~/Pictures/
                Vacations/
                Family/
        """
        if self._template is None:
            self.load()

        if not self._template or not self._template.get("roots"):
            return ""

        lines = ["Current folder organization:"]
        for root_path, tree in self._template["roots"].items():
            lines.append(f"  {root_path}/")
            self._render_tree(tree, lines, indent=4)

        return "\n".join(lines)

    def _render_tree(self, tree: dict, lines: List[str], indent: int) -> None:
        """Recursively render a tree dict into indented lines."""
        for name in sorted(tree.keys()):
            lines.append(f"{' ' * indent}{name}/")
            subtree = tree[name]
            if isinstance(subtree, dict) and subtree:
                self._render_tree(subtree, lines, indent + 2)

    def get_locations_for_category(self, category: str) -> List[str]:
        """Find existing folders whose name matches a category keyword."""
        if self._template is None:
            self.load()

        if not self._template or not self._template.get("roots"):
            return []

        category_lower = category.lower().replace("_", " ")
        matches: List[str] = []
        for root_path, tree in self._template["roots"].items():
            expanded = os.path.expanduser(root_path)
            self._find_category_dirs(tree, expanded, category_lower, matches)
        return matches

    def _find_category_dirs(
        self,
        tree: dict,
        parent_path: str,
        category: str,
        matches: List[str],
    ) -> None:
        """Recursively search for directories matching a category name."""
        for name, subtree in tree.items():
            full_path = os.path.join(parent_path, name)
            name_lower = name.lower().replace("_", " ").replace("-", " ")
            if category in name_lower or name_lower in category:
                matches.append(full_path)
            if isinstance(subtree, dict) and subtree:
                self._find_category_dirs(subtree, full_path, category, matches)
