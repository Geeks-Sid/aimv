"""Movement log tracking — records every file operation for audit and undo."""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class MoveRecord:
    """A single recorded file movement operation."""

    id: str = ""
    timestamp: str = ""
    source_path: str = ""
    destination_path: str = ""
    original_filename: str = ""
    new_filename: str = ""
    action: str = ""  # move, rename_and_move, create_folder_and_move, move_to_trash, dry_run
    rule_applied: Optional[str] = None
    file_hash: str = ""
    file_size: int = 0
    summary: str = ""
    reversible: bool = True
    reversed: bool = False
    created_dirs: List[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        source_path: str,
        destination_path: str,
        action: str,
        file_hash: str = "",
        file_size: int = 0,
        summary: str = "",
        rule_applied: Optional[str] = None,
        created_dirs: Optional[List[str]] = None,
        new_filename: Optional[str] = None,
    ) -> "MoveRecord":
        """Factory to create a new MoveRecord with auto-generated id and timestamp."""
        original_filename = os.path.basename(source_path)
        return cls(
            id=uuid.uuid4().hex[:12],
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_path=source_path,
            destination_path=destination_path,
            original_filename=original_filename,
            new_filename=new_filename or os.path.basename(destination_path),
            action=action,
            rule_applied=rule_applied,
            file_hash=file_hash,
            file_size=file_size,
            summary=summary,
            reversible=(action != "move_to_trash"),
            reversed=False,
            created_dirs=created_dirs or [],
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MoveRecord":
        return cls(
            id=data.get("id", ""),
            timestamp=data.get("timestamp", ""),
            source_path=data.get("source_path", ""),
            destination_path=data.get("destination_path", ""),
            original_filename=data.get("original_filename", ""),
            new_filename=data.get("new_filename", ""),
            action=data.get("action", ""),
            rule_applied=data.get("rule_applied"),
            file_hash=data.get("file_hash", ""),
            file_size=data.get("file_size", 0),
            summary=data.get("summary", ""),
            reversible=data.get("reversible", True),
            reversed=data.get("reversed", False),
            created_dirs=data.get("created_dirs", []),
        )


class MoveLog:
    """Append-only JSONL log of all file move operations."""

    def __init__(self, log_dir: str):
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "moves.jsonl")

    def record(self, record: MoveRecord) -> str:
        """Append a MoveRecord to the log. Returns the record ID."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record.id

    def _read_all(self) -> List[MoveRecord]:
        """Read every record from the log file."""
        if not os.path.exists(self.log_path):
            return []
        records: List[MoveRecord] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(MoveRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue
        return records

    def get_last(self, n: int = 10) -> List[MoveRecord]:
        """Return the last N records, most recent first."""
        all_records = self._read_all()
        return list(reversed(all_records[-n:]))

    def get_by_id(self, record_id: str) -> Optional[MoveRecord]:
        """Find a specific record by its ID."""
        for record in self._read_all():
            if record.id == record_id:
                return record
        return None

    def get_unreversed(self) -> List[MoveRecord]:
        """Return all records that haven't been undone, most recent first."""
        return list(
            reversed([r for r in self._read_all() if not r.reversed and r.reversible])
        )

    def mark_reversed(self, record_id: str) -> bool:
        """Rewrite the log with the specified record marked as reversed.

        This reads all records, flips the flag, and rewrites the file.
        Safe because the log is small and operations are infrequent.
        """
        records = self._read_all()
        found = False
        for record in records:
            if record.id == record_id:
                record.reversed = True
                found = True
                break

        if not found:
            return False

        tmp_path = self.log_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        os.replace(tmp_path, self.log_path)
        return True

    def search(self, query: str) -> List[MoveRecord]:
        """Search records by matching query against filenames, paths, and summaries."""
        query_lower = query.lower()
        results: List[MoveRecord] = []
        for record in self._read_all():
            searchable = " ".join([
                record.source_path,
                record.destination_path,
                record.original_filename,
                record.new_filename,
                record.summary,
                record.rule_applied or "",
            ]).lower()
            if query_lower in searchable:
                results.append(record)
        return list(reversed(results))
