"""Prepare file evidence and classify it through a typed decision provider."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aimv import config
from aimv.analyzers.image_analyzer import ImageAnalyzer
from aimv.analyzers.text_analyzer import TextAnalyzer
from aimv.classification.models import (
    ClassificationDecision,
    ClassificationPlan,
    FileEvidence,
)
from aimv.rules.matcher import build_rule_context_for_prompt, match_file
from aimv.rules.models import CategoryRule
from aimv.taxonomy.catalog import TaxonomyCatalog
from aimv.utils import file_utils
from aimv.utils.llm_utils import LLMHelper


class FileClassifier:
    """Hide extraction, provider routing, prompting, and response validation."""

    def __init__(
        self,
        rules: Sequence[CategoryRule],
        catalog: TaxonomyCatalog,
        llm_helper: Optional[LLMHelper] = None,
        decision_provider: Any = None,
        dependencies: Optional[Tuple[bool, bool, bool]] = None,
        candidate_limit: int = 12,
    ):
        self.rules = tuple(rules)
        self.catalog = catalog
        self.llm_helper = llm_helper
        self.decision_provider = decision_provider
        if self.llm_helper is None and self.decision_provider is None:
            raise ValueError("FileClassifier requires a decision provider")
        self.candidate_limit = max(1, candidate_limit)
        self.dependencies = dependencies or config.check_dependencies()

    def prepare(self, file_path: str) -> FileEvidence:
        path = os.path.abspath(file_path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")

        pypdf_installed, pillow_installed, pdf2image_installed = self.dependencies
        _, extension = os.path.splitext(path)
        extension = extension.lower()
        content_text = ""
        image_base64 = None

        if config.ALLOW_LLM_FILE_PROCESSING:
            try:
                if extension == ".pdf" and pypdf_installed:
                    ok, text = TextAnalyzer.extract_from_pdf(
                        path, config.MAX_EXTRACTED_TEXT_SIZE_KB
                    )
                    if ok and len(text.strip()) >= config.MIN_MEANINGFUL_TEXT_LENGTH:
                        content_text = text[:3000]
                    elif (
                        self.decision_provider is None
                        and config.ALLOW_LLM_IMAGE_PROCESSING
                        and pdf2image_installed
                        and pillow_installed
                    ):
                        image_base64 = ImageAnalyzer.pdf_to_image(
                            path,
                            config.MAX_IMAGE_RESOLUTION_FOR_LLM,
                            config.IMAGE_QUALITY_FOR_LLM,
                        )
                elif TextAnalyzer.is_text_file(path):
                    ok, text = TextAnalyzer.extract_from_text_file(
                        path, config.MAX_EXTRACTED_TEXT_SIZE_KB
                    )
                    if ok and len(text.strip()) >= config.MIN_MEANINGFUL_TEXT_LENGTH:
                        content_text = text[:3000]
                elif (
                    self.decision_provider is None
                    and ImageAnalyzer.is_image_file(path)
                    and config.ALLOW_LLM_IMAGE_PROCESSING
                    and pillow_installed
                ):
                    image_base64 = ImageAnalyzer.process_image(
                        path,
                        config.MAX_IMAGE_RESOLUTION_FOR_LLM,
                        config.IMAGE_QUALITY_FOR_LLM,
                    )
            except Exception as error:
                print(f"Content extraction error for {os.path.basename(path)}: {error}")

        matched_rule = None
        if self.rules and config.ENABLE_RULES_ENGINE:
            matched_rule = match_file(path, content_text[:500], list(self.rules))

        extracted = file_utils.check_if_archive_extracted(
            path, config.ARCHIVE_EXTENSIONS
        )
        archive_info = (
            f"Already extracted to '{os.path.basename(extracted)}'" if extracted else ""
        )

        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        try:
            modified = datetime.fromtimestamp(os.path.getmtime(path))
            modified_year, modified_month = modified.year, modified.month
        except OSError:
            modified_year, modified_month = datetime.now().year, datetime.now().month

        return FileEvidence(
            path=path,
            name=os.path.basename(path),
            extension=extension,
            type_description=TextAnalyzer.get_file_type_description(path),
            age_description=file_utils.get_file_age_description(path),
            size=size,
            content_text=content_text,
            image_base64=image_base64,
            archive_info=archive_info,
            deletable=extension in config.DELETABLE_CANDIDATE_EXTENSIONS,
            modified_year=modified_year,
            modified_month=modified_month,
            rule_name=matched_rule.name if matched_rule else None,
            rule_context=(
                build_rule_context_for_prompt(matched_rule) if matched_rule else ""
            ),
        )

    def classify(self, file_path: str) -> ClassificationPlan:
        evidence = self.prepare(file_path)
        needs_search = self.decision_provider is None or getattr(
            self.decision_provider, "uses_catalog_search", True
        )
        matches = (
            self.catalog.search(evidence.search_text, self.candidate_limit)
            if needs_search
            else ()
        )
        if self.decision_provider is not None:
            decision = self.decision_provider.decide(evidence, matches)
            if decision.bucket_id and not self.catalog.get(decision.bucket_id):
                raise ValueError(
                    f"Decision provider selected unknown bucket {decision.bucket_id}"
                )
            return ClassificationPlan(evidence, decision, evidence.rule_name)

        messages = self._build_messages(evidence, matches)
        schema = self._decision_schema(
            [match.bucket.id for match in matches]
        )
        raw = self.llm_helper.call_llm_json(
            messages,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.MAX_TOKENS_UNIFIED,
            json_schema=schema,
        )
        if not raw:
            raise RuntimeError("The classification agent returned no valid decision")
        decision = ClassificationDecision.from_mapping(raw)
        if decision.bucket_id and not self.catalog.get(decision.bucket_id):
            raise ValueError(
                f"Classification agent selected unknown bucket {decision.bucket_id}"
            )
        return ClassificationPlan(evidence, decision, evidence.rule_name)

    def _build_messages(self, evidence: FileEvidence, matches) -> List[Dict[str, Any]]:
        candidates = "\n".join(
            f"- {match.bucket.id} | {match.bucket.title} | "
            f"{match.bucket.relative_path} | {match.bucket.purpose}"
            for match in matches
        )
        system = (
            "You classify one file into a managed folder taxonomy. Respond with one JSON "
            "object and nothing else. For move, select exactly one bucket_id from CANDIDATES. "
            "Never return a filesystem path and never invent a bucket. Valid actions are move, "
            "trash, and stay. Return: action, bucket_id, name, year, month, tags, conf, "
            "reasoning. Extract year/month from the document's subject date, not the download "
            "date; use null when the content has no meaningful date. "
            "bucket_id is null for trash/stay. name is a basename only and preserves the file "
            "extension. Use trash only for clearly disposable material."
        )
        size = evidence.size
        size_text = (
            f"{size / 1024:.0f}KB"
            if size < 1_048_576
            else f"{size / 1_048_576:.1f}MB"
        )
        sections = [
            f"FILE: {evidence.name} | {evidence.type_description} | "
            f"{evidence.age_description} | {size_text}",
            f"CANDIDATES:\n{candidates}",
        ]
        if evidence.archive_info:
            sections.append(f"ARCHIVE: {evidence.archive_info}")
        if evidence.deletable:
            sections.append("DISPOSABLE_HINT: installer or temporary-file extension")
        if evidence.content_text:
            sections.append(f"CONTENT:\n{evidence.content_text[:2000]}")
        if evidence.rule_context:
            sections.append(f"LEGACY_RULE_GUIDANCE:\n{evidence.rule_context}")
        if config.CUSTOM_AI_INSTRUCTIONS.strip():
            sections.append(f"USER_GUIDELINES:\n{config.CUSTOM_AI_INSTRUCTIONS.strip()}")
        sections.append(
            "JSON example: "
            + json.dumps(
                {
                    "action": "move",
                    "bucket_id": "bucket.50.20.03",
                    "name": "2026-10-04_vendor_receipt.pdf",
                    "year": 2026,
                    "month": 10,
                    "tags": ["receipt", "vendor"],
                    "conf": 0.94,
                    "reasoning": "Purchase receipt",
                }
            )
        )
        user_text = "\n\n".join(sections)
        if evidence.image_base64:
            user_content: Any = [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{evidence.image_base64}"
                    },
                },
            ]
        else:
            user_content = user_text
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _decision_schema(candidate_ids: List[str]) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["move", "trash", "stay"],
                },
                "bucket_id": {
                    "type": ["string", "null"],
                    "enum": candidate_ids + [None],
                },
                "name": {"type": ["string", "null"]},
                "year": {
                    "type": ["integer", "null"],
                    "minimum": 1900,
                    "maximum": 2200,
                },
                "month": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "maximum": 12,
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "conf": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "reasoning": {"type": "string"},
            },
            "required": [
                "action",
                "bucket_id",
                "name",
                "year",
                "month",
                "tags",
                "conf",
                "reasoning",
            ],
            "additionalProperties": False,
        }
