import threading
import time

from aimv.batch import BatchOrganizer
from aimv.classification.models import (
    ClassificationDecision,
    ClassificationPlan,
    FileEvidence,
)
from aimv.organization.committer import OrganizationOutcome


class ConcurrentClassifier:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def classify(self, path):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.02)
        with self.lock:
            self.active -= 1
        evidence = FileEvidence(
            path=path,
            name=path.rsplit("/", 1)[-1],
            extension=".txt",
            type_description="text",
            age_description="recent",
            size=1,
        )
        return ClassificationPlan(
            evidence,
            ClassificationDecision(action="stay", confidence=1.0),
        )


class RecordingCommitter:
    def __init__(self):
        self.paths = []

    def commit(self, plan):
        self.paths.append(plan.evidence.path)
        return OrganizationOutcome(plan.evidence.path, "stayed", "kept")


def test_batch_classifies_concurrently_but_commits_in_input_order():
    paths = [f"/tmp/file-{number}.txt" for number in range(8)]
    classifier = ConcurrentClassifier()
    committer = RecordingCommitter()

    summary = BatchOrganizer(classifier, committer, workers=4).run(paths)

    assert classifier.max_active >= 2
    assert committer.paths == paths
    assert summary.succeeded == len(paths)
    assert summary.failed == 0
