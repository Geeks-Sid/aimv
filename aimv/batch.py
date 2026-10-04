"""Bounded parallel classification followed by controlled sequential commits."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from aimv.classification.classifier import FileClassifier
from aimv.classification.models import ClassificationPlan
from aimv.organization.committer import OrganizationCommitter, OrganizationOutcome


@dataclass(frozen=True)
class BatchSummary:
    outcomes: Tuple[OrganizationOutcome, ...]

    @property
    def succeeded(self) -> int:
        return sum(outcome.succeeded for outcome in self.outcomes)

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)

    @property
    def skipped(self) -> int:
        return sum(outcome.status == "skipped" for outcome in self.outcomes)


class BatchOrganizer:
    """Schedule independent classification workers, then commit in input order."""

    def __init__(
        self,
        classifier: FileClassifier,
        committer: OrganizationCommitter,
        workers: int = 4,
        on_classified: Optional[Callable[[int, int, str], None]] = None,
    ):
        self.classifier = classifier
        self.committer = committer
        self.workers = max(1, workers)
        self.on_classified = on_classified

    def run(self, file_paths: Sequence[str]) -> BatchSummary:
        total = len(file_paths)
        plans: List[Optional[ClassificationPlan]] = [None] * total
        errors: List[Optional[str]] = [None] * total

        with ThreadPoolExecutor(
            max_workers=min(self.workers, max(1, total)),
            thread_name_prefix="aimv-classifier",
        ) as executor:
            futures: Dict[Future, int] = {
                executor.submit(self.classifier.classify, path): position
                for position, path in enumerate(file_paths)
            }
            completed = 0
            for future in as_completed(futures):
                position = futures[future]
                try:
                    plans[position] = future.result()
                except Exception as error:
                    errors[position] = str(error)
                completed += 1
                if self.on_classified:
                    self.on_classified(completed, total, file_paths[position])

        outcomes: List[OrganizationOutcome] = []
        for position, path in enumerate(file_paths):
            if errors[position]:
                outcomes.append(
                    OrganizationOutcome(path, "failed", errors[position] or "Unknown error")
                )
                continue
            plan = plans[position]
            if plan is None:
                outcomes.append(
                    OrganizationOutcome(path, "failed", "Classification returned no plan")
                )
                continue
            outcomes.append(self.committer.commit(plan))

        return BatchSummary(tuple(outcomes))
