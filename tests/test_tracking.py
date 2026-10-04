"""Tests for movement tracking: MoveRecord, MoveLog, UndoManager."""

import os
import json
import tempfile
import shutil
import pytest

from aimv.tracking.move_log import MoveRecord, MoveLog
from aimv.tracking.undo import UndoManager
from aimv.index.file_index import FileIndex


# --------------------------------------------------------------------------- #
# MoveRecord
# --------------------------------------------------------------------------- #

class TestMoveRecord:
    def test_create(self):
        record = MoveRecord.create(
            source_path="/tmp/src/file.pdf",
            destination_path="/tmp/dst/file.pdf",
            action="move",
            file_hash="abc123",
            file_size=1024,
            summary="A test file",
        )
        assert record.id
        assert record.timestamp
        assert record.original_filename == "file.pdf"
        assert record.new_filename == "file.pdf"
        assert record.reversible is True
        assert record.reversed is False

    def test_create_trash_not_reversible(self):
        record = MoveRecord.create(
            source_path="/tmp/file.pdf",
            destination_path="/tmp/.Trash/file.pdf",
            action="move_to_trash",
        )
        assert record.reversible is False

    def test_to_dict_from_dict_roundtrip(self):
        record = MoveRecord.create(
            source_path="/a/b.txt",
            destination_path="/c/d.txt",
            action="rename_and_move",
            file_hash="hash",
            file_size=999,
            summary="test",
            rule_applied="receipts",
            created_dirs=["/c"],
            new_filename="d.txt",
        )
        d = record.to_dict()
        record2 = MoveRecord.from_dict(d)
        assert record.id == record2.id
        assert record.source_path == record2.source_path
        assert record.rule_applied == record2.rule_applied
        assert record.created_dirs == record2.created_dirs


# --------------------------------------------------------------------------- #
# MoveLog
# --------------------------------------------------------------------------- #

class TestMoveLog:
    @pytest.fixture
    def log_dir(self, tmp_path):
        return str(tmp_path / "logs")

    def _make_record(self, action="move", **kwargs):
        defaults = dict(
            source_path="/tmp/src/file.pdf",
            destination_path="/tmp/dst/file.pdf",
            action=action,
        )
        defaults.update(kwargs)
        return MoveRecord.create(**defaults)

    def test_record_and_read(self, log_dir):
        ml = MoveLog(log_dir)
        r = self._make_record()
        rid = ml.record(r)
        assert rid == r.id

        last = ml.get_last(5)
        assert len(last) == 1
        assert last[0].id == r.id

    def test_get_by_id(self, log_dir):
        ml = MoveLog(log_dir)
        r1 = self._make_record()
        r2 = self._make_record()
        ml.record(r1)
        ml.record(r2)

        found = ml.get_by_id(r1.id)
        assert found is not None
        assert found.id == r1.id

    def test_get_by_id_not_found(self, log_dir):
        ml = MoveLog(log_dir)
        assert ml.get_by_id("nonexistent") is None

    def test_get_unreversed(self, log_dir):
        ml = MoveLog(log_dir)
        r1 = self._make_record()
        r2 = self._make_record(action="move_to_trash")  # not reversible
        ml.record(r1)
        ml.record(r2)

        unreversed = ml.get_unreversed()
        assert len(unreversed) == 1
        assert unreversed[0].id == r1.id

    def test_mark_reversed(self, log_dir):
        ml = MoveLog(log_dir)
        r = self._make_record()
        ml.record(r)

        success = ml.mark_reversed(r.id)
        assert success

        found = ml.get_by_id(r.id)
        assert found.reversed is True

    def test_mark_reversed_not_found(self, log_dir):
        ml = MoveLog(log_dir)
        assert ml.mark_reversed("nonexistent") is False

    def test_get_last_ordering(self, log_dir):
        ml = MoveLog(log_dir)
        records = [self._make_record() for _ in range(5)]
        for r in records:
            ml.record(r)

        last3 = ml.get_last(3)
        assert len(last3) == 3
        # Most recent first
        assert last3[0].id == records[4].id
        assert last3[2].id == records[2].id

    def test_search(self, log_dir):
        ml = MoveLog(log_dir)
        r = self._make_record(summary="Nike return receipt")
        ml.record(r)

        results = ml.search("nike")
        assert len(results) == 1
        assert results[0].id == r.id

        assert ml.search("nonexistent") == []

    def test_empty_log(self, log_dir):
        ml = MoveLog(log_dir)
        assert ml.get_last(10) == []
        assert ml.get_unreversed() == []


# --------------------------------------------------------------------------- #
# UndoManager
# --------------------------------------------------------------------------- #

class TestUndoManager:
    @pytest.fixture
    def setup(self, tmp_path):
        """Create a temp environment with log, index, source and dest files."""
        log_dir = str(tmp_path / "logs")
        index_path = str(tmp_path / "index.json")
        src_dir = tmp_path / "source"
        dst_dir = tmp_path / "dest"
        src_dir.mkdir()
        dst_dir.mkdir()

        ml = MoveLog(log_dir)
        fi = FileIndex(index_path)
        undo = UndoManager(ml, fi)

        return {
            "tmp_path": tmp_path,
            "log_dir": log_dir,
            "index_path": index_path,
            "src_dir": src_dir,
            "dst_dir": dst_dir,
            "move_log": ml,
            "file_index": fi,
            "undo": undo,
        }

    def test_undo_last_no_records(self, setup):
        success, msg = setup["undo"].undo_last()
        assert not success
        assert "No reversible" in msg

    def test_undo_last_success(self, setup):
        src = setup["src_dir"] / "file.txt"
        dst = setup["dst_dir"] / "file.txt"
        src.write_text("hello")

        from aimv.utils.file_utils import compute_file_hash
        fhash = compute_file_hash(str(src))

        # Simulate the move
        shutil.move(str(src), str(dst))

        record = MoveRecord.create(
            source_path=str(src),
            destination_path=str(dst),
            action="move",
            file_hash=fhash,
            file_size=5,
        )
        setup["move_log"].record(record)

        success, msg = setup["undo"].undo_last()
        assert success
        assert os.path.exists(str(src))
        assert not os.path.exists(str(dst))

    def test_undo_by_id(self, setup):
        src = setup["src_dir"] / "doc.pdf"
        dst = setup["dst_dir"] / "doc.pdf"
        src.write_text("content")

        from aimv.utils.file_utils import compute_file_hash
        fhash = compute_file_hash(str(src))
        shutil.move(str(src), str(dst))

        record = MoveRecord.create(
            source_path=str(src), destination_path=str(dst),
            action="move", file_hash=fhash,
        )
        setup["move_log"].record(record)

        success, msg = setup["undo"].undo_by_id(record.id)
        assert success

    def test_undo_already_reversed(self, setup):
        dst = setup["dst_dir"] / "file.txt"
        dst.write_text("hello")

        record = MoveRecord.create(
            source_path=str(setup["src_dir"] / "file.txt"),
            destination_path=str(dst),
            action="move",
        )
        record.reversed = True
        setup["move_log"].record(record)

        success, msg = setup["undo"].undo_by_id(record.id)
        assert not success
        assert "already been reversed" in msg

    def test_undo_file_missing(self, setup):
        record = MoveRecord.create(
            source_path=str(setup["src_dir"] / "gone.txt"),
            destination_path=str(setup["dst_dir"] / "gone.txt"),
            action="move",
        )
        setup["move_log"].record(record)

        success, msg = setup["undo"].undo_last()
        assert not success
        assert "no longer exists" in msg

    def test_undo_cleans_created_dirs(self, setup):
        sub_dir = setup["dst_dir"] / "new_sub"
        sub_dir.mkdir()
        dst = sub_dir / "file.txt"
        src = setup["src_dir"] / "file.txt"
        src.write_text("data")

        from aimv.utils.file_utils import compute_file_hash
        fhash = compute_file_hash(str(src))
        shutil.move(str(src), str(dst))

        record = MoveRecord.create(
            source_path=str(src), destination_path=str(dst),
            action="create_folder_and_move", file_hash=fhash,
            created_dirs=[str(sub_dir)],
        )
        setup["move_log"].record(record)

        success, msg = setup["undo"].undo_last()
        assert success
        assert not os.path.exists(str(sub_dir))
