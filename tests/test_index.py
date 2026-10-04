"""Tests for the file index: IndexEntry, FileIndex."""

import os
import json
import pytest

from aimv.index.file_index import IndexEntry, FileIndex


class TestIndexEntry:
    def test_create(self):
        entry = IndexEntry.create(
            path="/docs/receipt.pdf",
            description="Nike purchase receipt",
            category="receipts",
            original_name="label.pdf",
            original_location="/tmp/Downloads/",
            move_id="abc123",
            tags=["nike", "receipt"],
        )
        assert entry.path == "/docs/receipt.pdf"
        assert entry.date_organized
        assert entry.tags == ["nike", "receipt"]

    def test_to_dict_excludes_path(self):
        entry = IndexEntry.create(path="/a/b.txt", description="test")
        d = entry.to_dict()
        assert "path" not in d
        assert "description" in d

    def test_from_dict(self):
        data = {
            "description": "A test file",
            "category": "general",
            "original_name": "old.txt",
            "original_location": "/tmp/",
            "date_organized": "2025-01-01T00:00:00",
            "move_id": "xyz",
            "tags": ["test"],
        }
        entry = IndexEntry.from_dict("/new/path.txt", data)
        assert entry.path == "/new/path.txt"
        assert entry.category == "general"
        assert entry.tags == ["test"]


class TestFileIndex:
    @pytest.fixture
    def index(self, tmp_path):
        return FileIndex(str(tmp_path / "index.json"))

    def _make_entry(self, path="/docs/file.pdf", **kwargs):
        defaults = dict(
            path=path,
            description="Test file",
            category="general",
        )
        defaults.update(kwargs)
        return IndexEntry.create(**defaults)

    def test_add_and_get(self, index):
        entry = self._make_entry()
        index.add_entry(entry)

        got = index.get_entry("/docs/file.pdf")
        assert got is not None
        assert got.description == "Test file"

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "index.json")
        idx1 = FileIndex(path)
        idx1.add_entry(self._make_entry())

        idx2 = FileIndex(path)
        idx2.load()
        assert idx2.get_entry("/docs/file.pdf") is not None

    def test_remove_entry(self, index):
        index.add_entry(self._make_entry())
        assert index.remove_entry("/docs/file.pdf") is True
        assert index.get_entry("/docs/file.pdf") is None

    def test_remove_nonexistent(self, index):
        assert index.remove_entry("/nope") is False

    def test_update_path(self, index):
        index.add_entry(self._make_entry(path="/old/path.pdf"))
        assert index.update_path("/old/path.pdf", "/new/path.pdf") is True
        assert index.get_entry("/old/path.pdf") is None
        assert index.get_entry("/new/path.pdf") is not None

    def test_search(self, index):
        index.add_entry(self._make_entry(
            path="/docs/nike_receipt.pdf",
            description="Nike purchase receipt",
            tags=["nike", "receipt"],
        ))
        index.add_entry(self._make_entry(
            path="/docs/homework.pdf",
            description="Physics homework solutions",
            tags=["physics"],
        ))

        results = index.search("nike")
        assert len(results) == 1
        assert results[0].path == "/docs/nike_receipt.pdf"

        results = index.search("physics")
        assert len(results) == 1

        assert index.search("nonexistent") == []

    def test_list_all(self, index):
        index.add_entry(self._make_entry(path="/a.pdf"))
        index.add_entry(self._make_entry(path="/b.pdf"))
        assert len(index.list_all()) == 2

    def test_list_by_category(self, index):
        index.add_entry(self._make_entry(path="/a.pdf", category="receipts"))
        index.add_entry(self._make_entry(path="/b.pdf", category="academic"))
        index.add_entry(self._make_entry(path="/c.pdf", category="receipts"))

        receipts = index.list_by_category("receipts")
        assert len(receipts) == 2

        academic = index.list_by_category("academic")
        assert len(academic) == 1

    def test_to_summary_string_empty(self, index):
        index.load()
        s = index.to_summary_string()
        assert "empty" in s.lower()

    def test_to_summary_string(self, index):
        index.add_entry(self._make_entry(path="/a.pdf", category="receipts"))
        s = index.to_summary_string()
        assert "receipts" in s
        assert "/a.pdf" in s

    def test_json_format(self, tmp_path):
        path = str(tmp_path / "index.json")
        idx = FileIndex(path)
        idx.add_entry(self._make_entry(path="/test.pdf"))

        with open(path, "r") as f:
            data = json.load(f)
        assert data["version"] == 1
        assert "last_updated" in data
        assert "/test.pdf" in data["entries"]
