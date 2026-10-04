import json

import pytest

from aimv.classification.models import FileEvidence
from aimv.classification.providers import (
    JevDecisionProvider,
    LayaDecisionProvider,
    extract_subject_period,
)
from aimv.classification import providers
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


def test_openrouter_jev_uses_decisions_api_with_complete_hierarchy(
    tmp_path, monkeypatch
):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    calls = []
    responses = iter(
        [
            {
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    "action": _choice("move", 0.98),
                    "area_id": _choice("area.70", 0.95),
                },
            },
            {
                "model": "typesafe/jev-1.13-20260917",
                "answers": {"category_id": _choice("category.70.60", 0.91)},
            },
            {
                "model": "typesafe/jev-1.13-20260917",
                "answers": {"bucket_id": _choice("bucket.70.60.02", 0.89)},
            },
        ]
    )

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request, timeout, json.loads(request.data)))
        return Response(next(responses))

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = JevDecisionProvider(catalog, api_key="secret")

    decision = provider.decide(_evidence("NIH R01 grant application"), [])

    assert decision.bucket_id == "bucket.70.60.02"
    assert decision.confidence == 0.89
    assert "typesafe/jev-1.13-20260917" in decision.reasoning
    assert len(calls) == 3
    assert calls[0][0].full_url == "https://openrouter.ai/api/alpha/decisions"
    assert calls[0][0].get_header("Authorization") == "Bearer secret"
    assert calls[0][2]["model"] == "typesafe/jev-1.13"
    assert len(calls[0][2]["questions"]["area_id"]["criteria"]) == 16
    assert len(calls[1][2]["questions"]["category_id"]["criteria"]) == 8
    assert len(calls[2][2]["questions"]["bucket_id"]["criteria"]) == 4


def test_openrouter_jev_requires_api_key(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    provider = JevDecisionProvider(catalog, api_key="")

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        provider.decide(_evidence(), [])
