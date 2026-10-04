"""File index — tracks all organized files with descriptions for fast lookup."""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class IndexEntry:
    """A single file tracked in the index."""

    path: str = ""
    description: str = ""
    category: str = "uncategorized"
    original_name: str = ""
    original_location: str = ""
    date_organized: str = ""
    move_id: str = ""
    tags: List[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        path: str,
        description: str,
        category: str = "uncategorized",
        original_name: str = "",
        original_location: str = "",
        move_id: str = "",
        tags: Optional[List[str]] = None,
    ) -> "IndexEntry":
        return cls(
            path=path,
            description=description,
            category=category,
            original_name=original_name,
            original_location=original_location,
            date_organized=datetime.now(timezone.utc).isoformat(),
            move_id=move_id,
            tags=tags or [],
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("path", None)
        return d

    @classmethod
    def from_dict(cls, path: str, data: dict) -> "IndexEntry":
        return cls(
            path=path,
            description=data.get("description", ""),
            category=data.get("category", "uncategorized"),
            original_name=data.get("original_name", ""),
            original_location=data.get("original_location", ""),
            date_organized=data.get("date_organized", ""),
            move_id=data.get("move_id", ""),
            tags=data.get("tags", []),
        )


class FileIndex:
    """JSON-backed file index mapping organized file paths to metadata."""

    VERSION = 1

    def __init__(self, index_path: str):
        self.index_path = index_path
        self._entries: Dict[str, IndexEntry] = {}
        self._loaded = False

    def load(self) -> None:
        """Read index.json into memory."""
        if not os.path.exists(self.index_path):
            self._entries = {}
            self._loaded = True
            return

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not load index from {self.index_path}: {e}")
            self._entries = {}
            self._loaded = True
            return

        entries_data = data.get("entries", {})
        self._entries = {
            path: IndexEntry.from_dict(path, entry_data)
            for path, entry_data in entries_data.items()
        }
        self._loaded = True

    def save(self) -> None:
        """Write index to disk with atomic write (tmp + rename)."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        data = {
            "version": self.VERSION,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "entries": {
                entry.path: entry.to_dict() for entry in self._entries.values()
            },
        }
        tmp_path = self.index_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, self.index_path)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def add_entry(self, entry: IndexEntry) -> None:
        """Add or overwrite an index entry keyed by its path."""
        self._ensure_loaded()
        previous = self._entries.get(entry.path)
        self._entries[entry.path] = entry
        try:
            self.save()
        except Exception:
            if previous is None:
                self._entries.pop(entry.path, None)
            else:
                self._entries[entry.path] = previous
            raise

    def remove_entry(self, path: str) -> bool:
        """Remove an entry by path. Returns True if it existed."""
        self._ensure_loaded()
        if path in self._entries:
            del self._entries[path]
            self.save()
            return True
        return False

    def update_path(self, old_path: str, new_path: str) -> bool:
        """Move an entry from old_path to new_path."""
        self._ensure_loaded()
        if old_path not in self._entries:
            return False
        entry = self._entries.pop(old_path)
        entry.path = new_path
        self._entries[new_path] = entry
        self.save()
        return True

    def get_entry(self, path: str) -> Optional[IndexEntry]:
        """Get a single entry by its path."""
        self._ensure_loaded()
        return self._entries.get(path)

    def search(self, query: str) -> List[IndexEntry]:
        """Search entries by matching query against description, tags, path, and category."""
        self._ensure_loaded()
        query_lower = query.lower()
        results: List[IndexEntry] = []
        for entry in self._entries.values():
            searchable = " ".join(
                [entry.path, entry.description, entry.category, entry.original_name]
                + entry.tags
            ).lower()
            if query_lower in searchable:
                results.append(entry)
        return results

    def list_all(self) -> List[IndexEntry]:
        """Return all entries sorted by date organized (most recent first)."""
        self._ensure_loaded()
        return sorted(
            self._entries.values(),
            key=lambda e: e.date_organized,
            reverse=True,
        )

    def list_by_category(self, category: str) -> List[IndexEntry]:
        """Filter entries by category name."""
        self._ensure_loaded()
        return [
            e
            for e in self._entries.values()
            if e.category.lower() == category.lower()
        ]

    def to_summary_string(self) -> str:
        """Render the index as a human-readable summary."""
        self._ensure_loaded()
        if not self._entries:
            return "File index is empty. No files have been organized yet."

        lines = [f"File Index ({len(self._entries)} files):", ""]
        by_category: Dict[str, List[IndexEntry]] = {}
        for entry in self._entries.values():
            by_category.setdefault(entry.category, []).append(entry)

        for category in sorted(by_category.keys()):
            entries = by_category[category]
            lines.append(f"  [{category}] ({len(entries)} files)")
            for entry in sorted(entries, key=lambda e: e.path):
                lines.append(f"    {entry.path}")
                lines.append(f"      {entry.description}")
            lines.append("")

        return "\n".join(lines)
