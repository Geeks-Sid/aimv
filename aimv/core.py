"""Compatibility facade for AIMV's classification and organization modules."""

from __future__ import annotations

import os
from typing import Callable, List, Optional, Tuple

from aimv import config
from aimv.classification.classifier import FileClassifier
from aimv.classification.models import ClassificationPlan
from aimv.classification.providers import LayaDecisionProvider
from aimv.index.file_index import FileIndex
from aimv.organization.committer import OrganizationCommitter, OrganizationOutcome
from aimv.rules.models import CategoryRule
from aimv.taxonomy.catalog import TaxonomyCatalog
from aimv.templates.org_template import OrgTemplate
from aimv.tracking.move_log import MoveLog
from aimv.utils.api_usage import get_tracker
from aimv.utils.llm_utils import LLMHelper


def create_llm_helper() -> LLMHelper:
    """Create the configured provider adapter with shared usage accounting."""
    tracker = get_tracker(
        config.AIMV_USAGE_PATH,
        config.MAX_API_CALLS_PER_DAY,
        config.MAX_API_CALLS_PER_MINUTE,
    )
    return LLMHelper(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE_URL,
        model_name=config.MODEL_NAME,
        max_retries=config.MAX_LLM_RETRIES_ON_PARSE_ERROR,
        usage_tracker=tracker,
    )


def create_file_classifier(
    rules: List[CategoryRule],
    catalog: TaxonomyCatalog,
    dependencies: Optional[Tuple[bool, bool, bool]] = None,
    llm_helper: Optional[LLMHelper] = None,
) -> FileClassifier:
    """Create the configured decision-provider adapter and classification Module."""
    provider_name = config.DECISION_PROVIDER
    if provider_name == "laya":
        decision_provider = LayaDecisionProvider(
            catalog=catalog,
            base_url=config.LAYA_BASE_URL,
            api_key=config.LAYA_API_KEY,
            model=config.LAYA_MODEL,
            preload=config.LAYA_PRELOAD,
        )
        helper = None
    elif provider_name in {"generative", "openai", "google"}:
        decision_provider = None
        helper = llm_helper or create_llm_helper()
    else:
        raise ValueError(
            f"Unsupported AIMV_DECISION_PROVIDER '{provider_name}'. "
            "Use 'laya' or 'generative'."
        )
    return FileClassifier(
        rules=rules,
        catalog=catalog,
        llm_helper=helper,
        decision_provider=decision_provider,
        dependencies=dependencies,
        candidate_limit=config.TAXONOMY_CANDIDATE_LIMIT,
    )


class SmartMover:
    """Backward-compatible single-file facade over the deep AIMV modules.

    Classification performs no filesystem mutation, so many calls may run in
    parallel. Applying a plan crosses the controlled organization commit seam.
    """

    def __init__(
        self,
        file_path_to_sort: str,
        rules: Optional[List[CategoryRule]] = None,
        move_log: Optional[MoveLog] = None,
        file_index: Optional[FileIndex] = None,
        org_template: Optional[OrgTemplate] = None,
        dry_run: bool = False,
        catalog: Optional[TaxonomyCatalog] = None,
        llm_helper: Optional[LLMHelper] = None,
        dependencies: Optional[Tuple[bool, bool, bool]] = None,
        confirm: Callable[[str], str] = input,
    ):
        del org_template  # Accepted for source compatibility with AIMV 0.1.
        self.file_path = os.path.abspath(file_path_to_sort)
        if not os.path.isfile(self.file_path):
            raise FileNotFoundError(f"File not found: {self.file_path}")

        self.catalog = catalog or TaxonomyCatalog.load_default(
            config.AIMV_TAXONOMY_ROOT
        )
        self.classifier = create_file_classifier(
            rules=rules or [],
            catalog=self.catalog,
            dependencies=dependencies,
            llm_helper=llm_helper,
        )
        self.committer = OrganizationCommitter(
            catalog=self.catalog,
            move_log=move_log,
            file_index=file_index,
            dry_run=dry_run,
            confirm=confirm,
        )

    def classify_file(self) -> ClassificationPlan:
        """Prepare and classify this file without moving or persisting it."""
        print(f"\n--- AIMV classify: {os.path.basename(self.file_path)} ---")
        plan = self.classifier.classify(self.file_path)
        decision = plan.decision
        print(
            f"Decision: action={decision.action} bucket={decision.bucket_id or '-'} "
            f"year={decision.year or '-'} month={decision.month or '-'} "
            f"confidence={decision.confidence:.2f}"
        )
        return plan

    def apply_classification(self, plan: ClassificationPlan) -> OrganizationOutcome:
        """Review and commit a previously classified immutable plan."""
        outcome = self.committer.commit(plan)
        destination = f" -> {outcome.destination_path}" if outcome.destination_path else ""
        print(f"{outcome.status.upper()}: {outcome.message}{destination}")
        return outcome

    def sort_file(self) -> OrganizationOutcome:
        """Classify and organize one file."""
        plan = self.classify_file()
        return self.apply_classification(plan)


if __name__ == "__main__":  # pragma: no cover - use the installed CLI
    import argparse

    parser = argparse.ArgumentParser(description="AIMV file organizer")
    parser.add_argument("file_path")
    parser.add_argument("--dry-run", action="store_true")
    parsed = parser.parse_args()
    SmartMover(parsed.file_path, dry_run=parsed.dry_run).sort_file()
