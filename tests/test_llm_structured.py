from concurrent.futures import ThreadPoolExecutor

from aimv.utils import llm_utils
from aimv.utils.api_usage import APIUsageTracker


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return type(
            "Response",
            (),
            {
                "output_text": (
                    '{"action":"stay","bucket_id":null,"name":null,'
                    '"year":null,"month":null,"tags":[],"conf":1,'
                    '"reasoning":"already organized"}'
                )
            },
        )()


class FakeOpenAI:
    def __init__(self, **kwargs):
        self.responses = FakeResponses()
        self.chat = type("Chat", (), {})()


def test_official_openai_uses_responses_structured_outputs(monkeypatch):
    monkeypatch.setattr(llm_utils, "OpenAI", FakeOpenAI)
    helper = llm_utils.LLMHelper(
        api_key="test",
        base_url="https://api.openai.com/v1",
        model_name="gpt-test",
        max_retries=0,
    )
    schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}},
        "required": ["action"],
        "additionalProperties": False,
    }

    result = helper.call_llm_json(
        [{"role": "user", "content": "classify"}], json_schema=schema
    )

    request = helper.client.responses.kwargs
    assert result["action"] == "stay"
    assert request["store"] is False
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["schema"] == schema


def test_usage_claims_are_atomic_across_workers(tmp_path):
    tracker = APIUsageTracker(str(tmp_path / "usage.json"), daily_limit=1000)

    with ThreadPoolExecutor(max_workers=8) as executor:
        totals = list(executor.map(lambda _: tracker.claim_call(), range(80)))

    assert sorted(totals) == list(range(1, 81))
    assert tracker.calls_today() == 80
