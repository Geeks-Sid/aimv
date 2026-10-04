"""Decision-provider adapters for generative models and Laya/Jev transports."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from aimv.classification.models import ClassificationDecision, FileEvidence
from aimv.taxonomy.catalog import BucketMatch, TaxonomyCatalog, TaxonomyNode


_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_YEAR_MONTH_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_/.](0?[1-9]|1[0-2])(?:[-_/.]\d{1,2})?(?!\d)"
)
_MONTH_YEAR_RE = re.compile(
    r"(?<!\d)(0?[1-9]|1[0-2])[-_/.]((?:19|20)\d{2})(?!\d)"
)
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def extract_subject_period(evidence: FileEvidence) -> Tuple[int, int]:
    """Extract a likely subject year/month, falling back to modification time."""
    text = f"{evidence.name} {evidence.content_text[:2000]}"
    numeric = _YEAR_MONTH_RE.search(text)
    if numeric:
        return int(numeric.group(1)), int(numeric.group(2))
    reverse_numeric = _MONTH_YEAR_RE.search(text)
    if reverse_numeric:
        return int(reverse_numeric.group(2)), int(reverse_numeric.group(1))

    lowered = text.lower()
    for month_name, month in _MONTHS.items():
        match = re.search(
            rf"\b{month_name}\b[^\d]{{0,16}}((?:19|20)\d{{2}})", lowered
        )
        if match:
            return int(match.group(1)), month
        match = re.search(
            rf"((?:19|20)\d{{2}})[^a-z]{{0,8}}\b{month_name}\b", lowered
        )
        if match:
            return int(match.group(1)), month

    year_match = _YEAR_RE.search(text)
    if year_match:
        return int(year_match.group(1)), evidence.modified_month
    return evidence.modified_year or datetime.now().year, evidence.modified_month or 1


class LayaDecisionProvider:
    """Classify with a local Laya Router or its Jev-compatible HTTP server."""

    supports_images = False
    uses_catalog_search = False

    def __init__(
        self,
        catalog: TaxonomyCatalog,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        preload: bool = True,
        timeout: int = 90,
        router: Any = None,
    ):
        self.catalog = catalog
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.preload = preload
        self.timeout = timeout
        self._router = router
        self._router_init_lock = threading.Lock()

    def decide(
        self, evidence: FileEvidence, matches: Sequence[BucketMatch]
    ) -> ClassificationDecision:
        del matches  # Laya traverses the complete hierarchy instead of pre-filtering.
        state = self._state(evidence)
        areas = self.catalog.children(None, "area")
        initial = self._predict(
            state,
            {
                "action": {
                    "type": "choice",
                    "instructions": "What should AIMV do with this file?",
                    "criteria": {
                        "move": "organize it into the managed taxonomy",
                        "stay": "it is already correctly organized and needs no move",
                        "trash": "it is clearly disposable, temporary, or a redundant extracted archive",
                    },
                },
                "area_id": self._choice_question(
                    "Which broad area best matches the file's subject and purpose?",
                    areas,
                ),
            },
        )
        action_answer = self._answer(initial, "action")
        area_answer = self._answer(initial, "area_id")
        action = str(action_answer.get("choice") or "move")
        action_confidence = self._answer_confidence(action_answer)
        year, month = extract_subject_period(evidence)
        route_name = (initial.get("routing") or {}).get("model") or self.model or "laya"

        if action != "move":
            return ClassificationDecision(
                action=action,
                confidence=action_confidence,
                reasoning=f"{route_name} selected {action}",
                year=year,
                month=month,
            )

        area = self._selected_node(areas, area_answer, "area")
        categories = self.catalog.children(area.id, "category")
        category_result = self._predict(
            state,
            {
                "category_id": self._choice_question(
                    f"Which category within {area.title} best matches this file?",
                    categories,
                )
            },
        )
        category_answer = self._answer(category_result, "category_id")
        category = self._selected_node(categories, category_answer, "category")

        buckets = self.catalog.children(category.id, "bucket")
        bucket_result = self._predict(
            state,
            {
                "bucket_id": self._choice_question(
                    f"Which final bucket within {category.title} best matches this file?",
                    buckets,
                    include_route=True,
                )
            },
        )
        bucket_answer = self._answer(bucket_result, "bucket_id")
        bucket = self._selected_node(buckets, bucket_answer, "bucket")
        confidence = min(
            action_confidence,
            self._answer_confidence(area_answer),
            self._answer_confidence(category_answer),
            self._answer_confidence(bucket_answer),
        )
        return ClassificationDecision(
            action="move",
            confidence=confidence,
            bucket_id=bucket.id,
            suggested_name=None,
            tags=tuple(bucket.tags[:10]),
            reasoning=(
                f"{route_name} selected {area.title} / {category.title} / {bucket.title}"
            ),
            year=year,
            month=month,
        )

    def _predict(self, state: dict, questions: dict) -> dict:
        return (
            self._http_predict(state, questions)
            if self.base_url
            else self._local_predict(state, questions)
        )

    def _local_predict(self, state: dict, questions: dict) -> dict:
        if self._router is None:
            with self._router_init_lock:
                if self._router is None:
                    try:
                        from laya import Router
                    except ImportError as error:
                        raise RuntimeError(
                            "Laya is selected but not installed. Install AIMV with the "
                            "'laya' extra or set LAYA_BASE_URL to a running laya-serve "
                            "instance."
                        ) from error
                    self._router = Router(preload=self.preload)
        kwargs = {"model": self.model} if self.model else {}
        return self._router.predict(state, questions, **kwargs)

    def _http_predict(self, state: dict, questions: dict) -> dict:
        payload: Dict[str, Any] = {"state": state, "questions": questions}
        if self.model:
            payload["model"] = self.model
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        endpoint = urljoin(self.base_url + "/", "v1/systemone")
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _state(evidence: FileEvidence) -> dict:
        return {
            "filename": evidence.name,
            "current_path": evidence.path,
            "file_type": evidence.type_description,
            "age": evidence.age_description,
            "content": evidence.content_text[:1400],
            "archive_state": evidence.archive_info,
            "disposable_extension": evidence.deletable,
            "legacy_rule": evidence.rule_name,
        }

    @staticmethod
    def _choice_question(
        instructions: str,
        nodes: Sequence[TaxonomyNode],
        include_route: bool = False,
    ) -> dict:
        if not nodes:
            raise ValueError("Taxonomy level has no decision options")
        return {
            "type": "choice",
            "instructions": instructions,
            "criteria": {
                node.id: (
                    f"{node.title}; {node.purpose}"
                    + (f"; folder route: {node.relative_path}" if include_route else "")
                )
                for node in nodes
            },
        }

    @staticmethod
    def _answer(result: dict, question_id: str) -> dict:
        answer = (result.get("answers") or {}).get(question_id)
        if not isinstance(answer, dict):
            raise ValueError(f"Laya response is missing answer {question_id}")
        return answer

    @staticmethod
    def _selected_node(
        nodes: Sequence[TaxonomyNode], answer: dict, level: str
    ) -> TaxonomyNode:
        selected = str(answer.get("choice") or "")
        for node in nodes:
            if node.id == selected:
                return node
        raise ValueError(f"Laya selected unknown {level} {selected or '<empty>'}")

    @staticmethod
    def _answer_confidence(answer: dict) -> float:
        value = answer.get("answer_confidence")
        if value is None:
            probabilities = answer.get("probabilities") or {}
            if probabilities:
                value = max(float(probability) for probability in probabilities.values())
        if value is None:
            value = answer.get("confidence", 0.0)
        return max(0.0, min(1.0, float(value)))
