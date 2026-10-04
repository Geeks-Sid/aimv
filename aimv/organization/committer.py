"""Validate and commit organization plans through one controlled writer path."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import Callable, Optional

from aimv import config
from aimv.classification.models import ClassificationPlan
from aimv.index.file_index import FileIndex, IndexEntry
from aimv.taxonomy.catalog import TaxonomyCatalog
from aimv.tracking.move_log import MoveLog, MoveRecord
from aimv.utils.file_utils import compute_file_hash


@dataclass(frozen=True)
class OrganizationOutcome:
    """A typed result for one classified file."""

    source_path: str
    status: str
    message: str
    destination_path: Optional[str] = None
    bucket_id: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.status in {"moved", "trashed", "stayed", "planned"}


class OrganizationCommitter:
    """Own path safety, review policy, moves, logging, and indexing."""

    def __init__(
        self,
        catalog: TaxonomyCatalog,
        move_log: Optional[MoveLog] = None,
        file_index: Optional[FileIndex] = None,
        dry_run: bool = False,
        trash_dir: Optional[str] = None,
        confirm: Callable[[str], str] = input,
    ):
        self.catalog = catalog
        self.move_log = move_log
        self.file_index = file_index
        self.dry_run = dry_run
        self.trash_dir = os.path.abspath(
            os.path.expanduser(trash_dir or os.path.join("~", ".Trash"))
        )
        self.confirm = confirm

    def commit(self, plan: ClassificationPlan) -> OrganizationOutcome:
        evidence = plan.evidence
        decision = plan.decision

        if decision.action == "stay":
            if (
                decision.confidence < config.HIGH_CONFIDENCE
                and not self.dry_run
                and self.confirm(
                    f"Keep '{evidence.name}' in place? (Y/n): "
                ).strip().lower()
                == "n"
            ):
                return OrganizationOutcome(
                    evidence.path, "skipped", "Stay decision declined"
                )
            return OrganizationOutcome(evidence.path, "stayed", "File stays in place")

        if decision.action == "trash":
            destination = self._unique_destination(
                os.path.join(self.trash_dir, evidence.name)
            )
            if self.dry_run:
                return OrganizationOutcome(
                    evidence.path,
                    "planned",
                    "Would move file to trash",
                    destination,
                )
            if self.confirm(f"Move '{evidence.name}' to Trash? (y/N): ").strip().lower() != "y":
                return OrganizationOutcome(
                    evidence.path, "skipped", "Trash decision declined"
                )
            os.makedirs(self.trash_dir, exist_ok=True)
            return self._move_and_record(plan, destination, "move_to_trash")

        if decision.confidence < config.MEDIUM_CONFIDENCE:
            return OrganizationOutcome(
                evidence.path,
                "skipped",
                f"Confidence {decision.confidence:.2f} is below the move threshold",
                bucket_id=decision.bucket_id,
            )

        if not decision.bucket_id:
            return OrganizationOutcome(
                evidence.path, "failed", "Move decision has no bucket ID"
            )

        try:
            bucket = self.catalog.get(decision.bucket_id)
            if bucket is None or bucket.kind != "bucket":
                raise KeyError(f"Unknown bucket ID: {decision.bucket_id}")
            year = decision.year or evidence.modified_year
            month = decision.month or evidence.modified_month
            target_dir = self.catalog.resolve(decision.bucket_id)
            if bucket.partition in {"year", "year_month"}:
                target_dir = os.path.join(target_dir, str(year))
            if bucket.partition == "year_month":
                target_dir = os.path.join(target_dir, f"{year}-{month:02d}")
            self._assert_inside_root(target_dir)
            filename = self._validated_filename(
                evidence.name, decision.suggested_name
            )
        except (KeyError, ValueError) as error:
            return OrganizationOutcome(
                evidence.path,
                "failed",
                str(error),
                bucket_id=decision.bucket_id,
            )

        destination = self._unique_destination(os.path.join(target_dir, filename))
        if decision.confidence < config.HIGH_CONFIDENCE and not self.dry_run:
            response = self.confirm(
                f"Move '{filename}' to bucket {decision.bucket_id} ({target_dir})? (y/N): "
            )
            if response.strip().lower() != "y":
                return OrganizationOutcome(
                    evidence.path,
                    "skipped",
                    "Move decision declined",
                    destination,
                    decision.bucket_id,
                )

        if self.dry_run:
            return OrganizationOutcome(
                evidence.path,
                "planned",
                "Would move file",
                destination,
                decision.bucket_id,
            )

        self.catalog.materialize([decision.bucket_id])
        self._materialize_partition_metadata(
            decision.bucket_id, target_dir, decision.year or evidence.modified_year,
            decision.month or evidence.modified_month,
        )
        return self._move_and_record(plan, destination, "move")

    def _materialize_partition_metadata(
        self, bucket_id: str, target_dir: str, year: int, month: int
    ) -> None:
        bucket = self.catalog.get(bucket_id)
        if bucket is None or bucket.partition == "none":
            return
        import yaml

        bucket_dir = self.catalog.resolve(bucket_id)
        year_dir = os.path.join(bucket_dir, str(year))
        paths = [(year_dir, f"{bucket_id}.year.{year}", "year", str(year))]
        if bucket.partition == "year_month":
            paths.append(
                (
                    os.path.join(year_dir, f"{year}-{month:02d}"),
                    f"{bucket_id}.month.{year}-{month:02d}",
                    "month",
                    f"{year}-{month:02d}",
                )
            )
        parent_id = bucket_id
        for path, node_id, kind, title in paths:
            os.makedirs(path, exist_ok=True)
            metadata_path = os.path.join(path, ".aimv-folder.yaml")
            if not os.path.exists(metadata_path):
                with open(metadata_path + ".tmp", "w", encoding="utf-8") as stream:
                    yaml.safe_dump(
                        {
                            "schema_version": 1,
                            "id": node_id,
                            "code": title,
                            "title": title,
                            "kind": "partition",
                            "relative_path": os.path.relpath(path, self.catalog.root),
                            "parent_id": parent_id,
                            "purpose": f"{bucket.title} files for {title}.",
                            "aliases": [],
                            "tags": list(bucket.tags) + [title],
                            "include": [],
                            "exclude": [],
                            "partition": "none",
                        },
                        stream,
                        sort_keys=False,
                    )
                os.replace(metadata_path + ".tmp", metadata_path)
            parent_id = node_id

    def _move_and_record(
        self, plan: ClassificationPlan, destination: str, action: str
    ) -> OrganizationOutcome:
        evidence = plan.evidence
        decision = plan.decision
        file_hash = compute_file_hash(evidence.path) or ""
        try:
            file_size = os.path.getsize(evidence.path)
        except OSError:
            file_size = 0

        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.move(evidence.path, destination)
        except OSError as error:
            return OrganizationOutcome(
                evidence.path,
                "failed",
                f"Move failed: {error}",
                destination,
                decision.bucket_id,
            )

        record_id = ""
        try:
            if self.move_log and config.ENABLE_MOVE_LOGGING:
                record = MoveRecord.create(
                    source_path=evidence.path,
                    destination_path=destination,
                    action=action,
                    file_hash=file_hash,
                    file_size=file_size,
                    summary=evidence.summary,
                    rule_applied=plan.rule_name,
                    new_filename=os.path.basename(destination),
                )
                record_id = self.move_log.record(record)

            if (
                self.file_index
                and config.ENABLE_FILE_INDEX
                and action != "move_to_trash"
            ):
                self.file_index.add_entry(
                    IndexEntry.create(
                        path=destination,
                        description=evidence.summary,
                        category=decision.bucket_id or "uncategorized",
                        original_name=evidence.name,
                        original_location=os.path.dirname(evidence.path),
                        move_id=record_id,
                        tags=list(decision.tags),
                    )
                )
        except Exception as error:
            rollback_error = None
            rolled_back = False
            try:
                if os.path.exists(destination) and not os.path.exists(evidence.path):
                    shutil.move(destination, evidence.path)
                    rolled_back = True
            except OSError as rollback:
                rollback_error = rollback
            compensation_error = None
            if rolled_back and record_id and self.move_log:
                try:
                    self.move_log.mark_reversed(record_id)
                except Exception as compensation:
                    compensation_error = compensation
            message = f"Persistence failed after move: {error}"
            if rollback_error:
                message += f"; rollback also failed: {rollback_error}"
            if compensation_error:
                message += f"; log compensation also failed: {compensation_error}"
            return OrganizationOutcome(
                evidence.path,
                "failed",
                message,
                destination,
                decision.bucket_id,
            )

        status = "trashed" if action == "move_to_trash" else "moved"
        return OrganizationOutcome(
            evidence.path,
            status,
            f"File {status}",
            destination,
            decision.bucket_id,
        )

    def _assert_inside_root(self, path: str) -> None:
        root = os.path.realpath(self.catalog.root)
        candidate = os.path.realpath(path)
        try:
            common = os.path.commonpath((root, candidate))
        except ValueError as error:
            raise ValueError("Destination is outside the taxonomy root") from error
        if common != root:
            raise ValueError("Destination is outside the taxonomy root")

    @staticmethod
    def _validated_filename(original: str, suggested: Optional[str]) -> str:
        filename = suggested or original
        if filename != os.path.basename(filename) or filename in {"", ".", ".."}:
            raise ValueError("Suggested filename is unsafe")
        if re.search(r"[\\/:*?\"<>|]", filename):
            raise ValueError("Suggested filename contains invalid characters")
        original_extension = os.path.splitext(original)[1].lower()
        suggested_extension = os.path.splitext(filename)[1].lower()
        if original_extension and suggested_extension != original_extension:
            raise ValueError("Suggested filename must preserve the original extension")
        return filename

    @staticmethod
    def _unique_destination(path: str) -> str:
        if not os.path.exists(path):
            return path
        stem, extension = os.path.splitext(path)
        counter = 1
        candidate = f"{stem}_{counter}{extension}"
        while os.path.exists(candidate):
            counter += 1
            candidate = f"{stem}_{counter}{extension}"
        return candidate
