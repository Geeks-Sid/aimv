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
        area="50-money-and-finance",
        category="50-money-and-finance/50-20-income-and-spending",
        bucket=(
            "50-money-and-finance/50-20-income-and-spending/"
            "50-20-03-invoices-and-bills"
        ),
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
    route = (
        "50-money-and-finance/50-20-income-and-spending/"
        "50-20-03-invoices-and-bills"
    )
    assert route in bucket_criteria
    assert "folder route:" in bucket_criteria[route]


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
        area="70-education-and-research",
        category="70-education-and-research/70-60-grants-and-research-funding",
        bucket=(
            "70-education-and-research/70-60-grants-and-research-funding/"
            "70-60-02-proposals-and-applications"
        ),
    )
    provider = LayaDecisionProvider(catalog=catalog, router=router)

    decision = provider.decide(_evidence("NIH R01 grant application"), [])

    assert decision.bucket_id == "bucket.70.60.02"
    assert len(router.calls[1][1]["category_id"]["criteria"]) == 8
    route = (
        "70-education-and-research/70-60-grants-and-research-funding/"
        "70-60-02-proposals-and-applications"
    )
    assert route in router.calls[2][1]["bucket_id"]["criteria"]


def test_tax_income_form_path_is_provider_visible_and_explicit(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    buckets = catalog.children("category.50.40", "bucket")

    question = LayaDecisionProvider._choice_question(
        "Which tax bucket?", buckets, include_route=True
    )
    route = (
        "50-money-and-finance/50-40-taxes/"
        "50-40-02-w-2-1099-and-income-forms"
    )

    assert route in question["criteria"]
    assert "W-2" in question["criteria"][route]
    assert "1099" in question["criteria"][route]
    assert "K-1" in question["criteria"][route]
    assert all(" " not in option for option in question["criteria"])


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
    assert extract_subject_period(
        _evidence(content="Statement period January 1 through January 31, 2024")
    ) == (2024, 1)


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
                    "area_id": _choice("70-education-and-research", 0.95),
                },
            },
            {
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    "category_id": _choice(
                        "70-education-and-research/"
                        "70-60-grants-and-research-funding",
                        0.91,
                    )
                },
            },
            {
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    "bucket_id": _choice(
                        "70-education-and-research/"
                        "70-60-grants-and-research-funding/"
                        "70-60-02-proposals-and-applications",
                        0.89,
                    )
                },
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
