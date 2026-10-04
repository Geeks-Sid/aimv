from aimv.classification.models import FileEvidence
from aimv.classification.providers import LayaDecisionProvider, extract_subject_period
from aimv.taxonomy.catalog import TaxonomyCatalog


def _choice(choice, confidence):
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": {choice: confidence},
        "answer_confidence": confidence,
        "confidence": confidence,
    }


class HierarchyRouter:
    def __init__(
        self,
        action="move",
        area="area.50",
        category="category.50.20",
        bucket="bucket.50.20.03",
    ):
        self.action = action
        self.area = area
        self.category = category
        self.bucket = bucket
        self.calls = []

    def predict(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if "action" in questions:
            return {
                "answers": {
                    "action": _choice(self.action, 0.96),
                    "area_id": _choice(self.area, 0.91),
                },
                "routing": {"model": "english"},
            }
        if "category_id" in questions:
            return {
                "answers": {"category_id": _choice(self.category, 0.88)}
            }
        return {"answers": {"bucket_id": _choice(self.bucket, 0.84)}}


def _evidence(content="Invoice dated July 2024"):
    return FileEvidence(
        path="/tmp/invoice.pdf",
        name="invoice.pdf",
        extension=".pdf",
        type_description="PDF document",
        age_description="recent",
        size=100,
        content_text=content,
        modified_year=2026,
        modified_month=10,
    )


def test_laya_considers_every_bucket_through_small_hierarchical_choices(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    router = HierarchyRouter()
    provider = LayaDecisionProvider(catalog=catalog, router=router)

    decision = provider.decide(_evidence(), [])

    assert decision.bucket_id == "bucket.50.20.03"
    assert decision.year == 2024
    assert decision.month == 7
    assert decision.confidence == 0.84
    assert decision.suggested_name is None
    assert len(router.calls) == 3
    assert len(router.calls[0][1]["area_id"]["criteria"]) == 16
    assert len(router.calls[1][1]["category_id"]["criteria"]) == 5
    assert len(router.calls[2][1]["bucket_id"]["criteria"]) == 4
    bucket_criteria = router.calls[2][1]["bucket_id"]["criteria"]
    assert "folder route:" in bucket_criteria["bucket.50.20.03"]
    assert "50.20.03 Invoices & Bills" in bucket_criteria["bucket.50.20.03"]


def test_laya_stay_or_trash_stops_after_first_decision(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    router = HierarchyRouter(action="stay")
    provider = LayaDecisionProvider(catalog=catalog, router=router)

    decision = provider.decide(_evidence(), [])

    assert decision.action == "stay"
    assert decision.bucket_id is None
    assert len(router.calls) == 1


def test_laya_reaches_expanded_research_categories(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    router = HierarchyRouter(
        area="area.70",
        category="category.70.60",
        bucket="bucket.70.60.02",
    )
    provider = LayaDecisionProvider(catalog=catalog, router=router)

    decision = provider.decide(_evidence("NIH R01 grant application"), [])

    assert decision.bucket_id == "bucket.70.60.02"
    assert len(router.calls[1][1]["category_id"]["criteria"]) == 8
    assert "70.60.02 Proposals & Applications" in (
        router.calls[2][1]["bucket_id"]["criteria"]["bucket.70.60.02"]
    )


def test_subject_period_falls_back_to_file_metadata():
    evidence = _evidence(content="No document date here")

    assert extract_subject_period(evidence) == (2026, 10)


def test_subject_period_supports_month_first_and_named_dates():
    assert extract_subject_period(_evidence(content="Statement for 07/2024")) == (
        2024,
        7,
    )
    assert extract_subject_period(_evidence(content="Statement for September 2023")) == (
        2023,
        9,
    )
