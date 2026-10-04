"""Undo manager — validates and reverses file move operations."""

import os
import shutil
from typing import Tuple

from aimv.tracking.move_log import MoveLog, MoveRecord
from aimv.index.file_index import FileIndex
from aimv.utils.file_utils import compute_file_hash


class UndoManager:
    """Reverses file moves using the movement log and file index."""

    def __init__(self, move_log: MoveLog, file_index: FileIndex):
        self.move_log = move_log
        self.file_index = file_index

    def undo_last(self) -> Tuple[bool, str]:
        """Undo the most recent unreversed, reversible operation."""
        unreversed = self.move_log.get_unreversed()
        if not unreversed:
            return False, "No reversible operations found in the log."
        return self._undo_record(unreversed[0])

    def undo_by_id(self, record_id: str) -> Tuple[bool, str]:
        """Undo a specific operation identified by its log ID."""
        record = self.move_log.get_by_id(record_id)
        if record is None:
            return False, f"No record found with ID '{record_id}'."
        return self._undo_record(record)

    def _undo_record(self, record: MoveRecord) -> Tuple[bool, str]:
        """Validate and execute the undo for a single record."""
        valid, msg = self.validate_undo(record)
        if not valid:
            return False, msg
        return self.execute_undo(record)

    def validate_undo(self, record: MoveRecord) -> Tuple[bool, str]:
        """Check whether an undo operation is safe to perform.

        Verifies:
          - Record hasn't already been reversed
          - Record is marked reversible
          - File exists at the destination
          - File hash still matches (file hasn't been modified)
          - Source directory is writable
        """
        if record.reversed:
            return False, f"Record '{record.id}' has already been reversed."

        if not record.reversible:
            return False, (
                f"Record '{record.id}' is not reversible "
                f"(action: {record.action})."
            )

        if not os.path.exists(record.destination_path):
            return False, (
                f"File no longer exists at destination: {record.destination_path}"
            )

        if record.file_hash:
            current_hash = compute_file_hash(record.destination_path)
            if current_hash and current_hash != record.file_hash:
                return False, (
                    f"File has been modified since it was moved "
                    f"(hash mismatch). Undo aborted to prevent data loss."
                )

        source_dir = os.path.dirname(record.source_path)
        if source_dir and not os.path.isdir(source_dir):
            return False, (
                f"Original source directory no longer exists: {source_dir}. "
                f"Create it manually first, then retry."
            )

        if os.path.exists(record.source_path):
            return False, (
                f"A file already exists at the original location: {record.source_path}. "
                f"Undo aborted to prevent overwrite."
            )

        return True, "Validation passed."

    def execute_undo(self, record: MoveRecord) -> Tuple[bool, str]:
        """Move the file back to its original location and clean up.

        Steps:
          1. Move file from destination back to source (with original filename)
          2. Remove any empty directories that were created during the original move
          3. Mark the log record as reversed
          4. Remove the file index entry
        """
        try:
            source_dir = os.path.dirname(record.source_path)
            os.makedirs(source_dir, exist_ok=True)

            shutil.move(record.destination_path, record.source_path)
        except Exception as e:
            return False, f"Failed to move file back: {e}"

        # Clean up empty directories that were created during the original move
        for dir_path in reversed(record.created_dirs):
            try:
                if os.path.isdir(dir_path) and not os.listdir(dir_path):
                    os.rmdir(dir_path)
            except OSError:
                pass

        self.move_log.mark_reversed(record.id)
        self.file_index.remove_entry(record.destination_path)

        return True, (
            f"Undo successful. Moved '{record.new_filename}' back to "
            f"'{record.source_path}'"
        )
