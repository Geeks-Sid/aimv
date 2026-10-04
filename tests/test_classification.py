import pytest

from aimv import core
from aimv.classification.classifier import FileClassifier
from aimv.classification.models import ClassificationDecision
from aimv.taxonomy.catalog import TaxonomyCatalog


def test_classification_decision_validates_typed_fields():
    decision = ClassificationDecision.from_mapping(
        {
            "action": "move",
            "bucket_id": "bucket.50.20.03",
            "name": "2025-03_vendor_invoice.pdf",
            "year": 2025,
            "month": 3,
            "tags": ["Invoice", "Vendor", "invoice"],
            "conf": 0.91,
            "reasoning": "A vendor invoice",
        }
    )

    assert decision.year == 2025
    assert decision.month == 3
    assert decision.tags == ("invoice", "vendor")


@pytest.mark.parametrize("name", ["../escape.pdf", "nested/file.pdf", "/tmp/file.pdf"])
def test_classification_decision_rejects_path_in_filename(name):
    with pytest.raises(ValueError, match="must not contain a path"):
        ClassificationDecision.from_mapping(
            {
                "action": "move",
                "bucket_id": "bucket.50.20.03",
                "name": name,
                "conf": 0.9,
            }
        )


def test_structured_decision_schema_constrains_bucket_route():
    schema = FileClassifier._decision_schema(
        ["bucket.50.10.01", "bucket.50.20.03"]
    )

    assert schema["properties"]["bucket_id"]["enum"] == [
        "bucket.50.10.01",
        "bucket.50.20.03",
        None,
    ]
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False


def test_hierarchical_provider_skips_candidate_search(tmp_path):
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"test")

    class Catalog:
        def contains_path(self, _path):
            return False

        def search(self, *_args, **_kwargs):
            raise AssertionError("hierarchical Laya must not prefilter buckets")

        def get(self, _bucket_id):
            return None

    class Provider:
        uses_catalog_search = False

        def decide(self, _evidence, matches):
            assert matches == ()
            return ClassificationDecision(action="stay", confidence=1.0)

    classifier = FileClassifier(
        rules=[],
        catalog=Catalog(),
        decision_provider=Provider(),
        dependencies=(False, False, False),
    )

    assert classifier.classify(str(source)).decision.action == "stay"


def test_generative_helper_factory_returns_configured_helper(monkeypatch):
    tracker = object()
    captured = {}

    class FakeHelper:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(core, "get_tracker", lambda *_args: tracker)
    monkeypatch.setattr(core, "LLMHelper", FakeHelper)

    helper = core.create_llm_helper()

    assert isinstance(helper, FakeHelper)
    assert captured["usage_tracker"] is tracker
    assert captured["model_name"] == core.config.MODEL_NAME


def test_file_already_in_managed_root_never_calls_provider(tmp_path):
    root = tmp_path / "AIMV"
    root.mkdir()
    source = root / "already-managed.txt"
    source.write_text("already managed")
    catalog = TaxonomyCatalog.load_default(str(root))

    class Provider:
        uses_catalog_search = False

        def decide(self, *_args):
            raise AssertionError("managed files must not reach a provider")

    classifier = FileClassifier(
        rules=[],
        catalog=catalog,
        decision_provider=Provider(),
        dependencies=(False, False, False),
    )

    decision = classifier.classify(str(source)).decision

    assert decision.action == "stay"
    assert decision.confidence == 1.0
    assert "already inside" in decision.reasoning
