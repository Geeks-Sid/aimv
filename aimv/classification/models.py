"""Typed values passed between parallel classification and serialized commits."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class FileEvidence:
    """Locally extracted evidence used to classify one file."""

    path: str
    name: str
    extension: str
    type_description: str
    age_description: str
    size: int
    content_text: str = ""
    image_base64: Optional[str] = None
    archive_info: str = ""
    deletable: bool = False
    modified_year: int = 0
    modified_month: int = 0
    rule_name: Optional[str] = None
    rule_context: str = ""

    @property
    def summary(self) -> str:
        return (self.content_text[:200] or self.type_description).strip()

    @property
    def search_text(self) -> str:
        return " ".join(
            value
            for value in (
                self.name,
                self.type_description,
                self.rule_name or "",
                self.content_text[:1200],
            )
            if value
        )


@dataclass(frozen=True)
class ClassificationDecision:
    """Validated, provider-independent organization decision."""

    action: str
    confidence: float
    bucket_id: Optional[str] = None
    suggested_name: Optional[str] = None
    tags: Tuple[str, ...] = field(default_factory=tuple)
    reasoning: str = ""
    year: Optional[int] = None
    month: Optional[int] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ClassificationDecision":
        action = str(data.get("action") or "").strip().lower()
        aliases = {"move_to_trash": "trash", "keep": "stay"}
        action = aliases.get(action, action)
        if action not in {"move", "trash", "stay"}:
            raise ValueError(f"Unsupported classification action: {action or '<empty>'}")

        raw_confidence = data.get("conf", data.get("confidence", 0.0))
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError) as error:
            raise ValueError("Classification confidence must be numeric") from error
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Classification confidence must be between 0 and 1")

        bucket_id = data.get("bucket_id", data.get("bucket"))
        if bucket_id is not None:
            bucket_id = str(bucket_id).strip() or None
        if action == "move" and not bucket_id:
            raise ValueError("Move decisions require a bucket_id")

        suggested_name = data.get("name")
        if suggested_name is not None:
            suggested_name = str(suggested_name).strip() or None
        if suggested_name:
            if suggested_name != os.path.basename(suggested_name):
                raise ValueError("Suggested filename must not contain a path")
            if suggested_name in {".", ".."}:
                raise ValueError("Suggested filename is unsafe")

        raw_tags = data.get("tags") or ()
        if not isinstance(raw_tags, (list, tuple)):
            raise ValueError("Classification tags must be a list")
        tags = tuple(
            dict.fromkeys(
                str(tag).strip().lower()
                for tag in raw_tags
                if str(tag).strip()
            )
        )[:10]

        year = cls._optional_int(data.get("year"), "year")
        month = cls._optional_int(data.get("month"), "month")
        if year is not None and not 1900 <= year <= 2200:
            raise ValueError("Classification year is outside the supported range")
        if month is not None and not 1 <= month <= 12:
            raise ValueError("Classification month must be between 1 and 12")

        return cls(
            action=action,
            confidence=confidence,
            bucket_id=bucket_id,
            suggested_name=suggested_name,
            tags=tags,
            reasoning=str(data.get("reasoning") or "").strip(),
            year=year,
            month=month,
        )

    @staticmethod
    def _optional_int(value: Any, field_name: str) -> Optional[int]:
        if value in (None, "", "null", "none"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Classification {field_name} must be an integer or null") from error


@dataclass(frozen=True)
class ClassificationPlan:
    """The immutable handoff from a classification worker to the commit stage."""

    evidence: FileEvidence
    decision: ClassificationDecision
    rule_name: Optional[str] = None
