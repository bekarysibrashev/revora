import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.modules.ai.call_quality.audio import RecordingLoader
from app.modules.ai.call_quality.intelligence import (
    CallIntelligenceError,
    CallReport,
    GroqCallIntelligenceClient,
    OpenAICallIntelligenceClient,
)
from app.modules.ai.call_quality.models import CallQualityAnalysis
from app.modules.ai.call_quality.pipeline import CallQualityPipeline


def rule_payload() -> dict:
    return {
        "criteria": [
            {"name": "Приветствие", "weight": 25},
            {"name": "Запись", "weight": 75},
        ]
    }


def report_payload(*, score: int = 91, confidence: float = 0.9) -> dict:
    return {
        "result": "success",
        "score": score,
        "summary": "Оператор выявил потребность и предложил запись.",
        "operator_speaker": "A",
        "customer_speaker": "B",
        "languages": ["ru", "kk"],
        "mixed_language": True,
        "confidence": confidence,
        "needs_review": False,
        "criteria_scores": [
            {"name": "Приветствие", "score": 80, "explanation": "Разговор начат корректно."},
            {"name": "Запись", "score": 100, "explanation": "Предложено конкретное время."},
        ],
        "strengths": ["Выявил потребность"],
        "loss_reasons": [],
        "recommendations": ["Не перебивать клиента"],
        "flags": {
            "operator_interrupted_customer": False,
            "appointment_not_offered": False,
            "price_without_explanation": False,
            "possible_conflict": False,
            "personal_data_spoken": False,
        },
        "evidence": [{
            "criterion": "Запись",
            "timestamp_from": 5.0,
            "timestamp_to": 7.5,
            "description": "Оператор предложил конкретное время.",
        }],
    }


@pytest.mark.asyncio
async def test_openai_call_client_uses_diarization_and_structured_private_report() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/audio/transcriptions"):
            assert b"diarized_json" in request.content
            assert b"chunking_strategy" in request.content and b"auto" in request.content
            return httpx.Response(200, json={
                "duration": 12.0,
                "segments": [
                    {"speaker": "A", "start": 0, "end": 4, "text": "Клиника, здравствуйте"},
                    {"speaker": "B", "start": 4, "end": 8, "text": "Ертең запись бар ма?"},
                ],
            })
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["type"] == "json_schema"
        scores = body["text"]["format"]["schema"]["properties"]["criteria_scores"]
        assert scores["items"]["properties"]["name"]["enum"] == [
            "Приветствие",
            "Запись",
        ]
        assert "minItems" not in scores and "maxItems" not in scores
        return httpx.Response(200, json={
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(report_payload(), ensure_ascii=False)}],
            }]
        })

    client = OpenAICallIntelligenceClient(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        transcription_model="gpt-4o-transcribe-diarize",
        analysis_model="test-analysis",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    transcript = await client.transcribe(
        b"fake-mp3", filename="test.mp3", content_type="audio/mpeg"
    )
    report = await client.analyze(transcript, rule_payload())
    assert transcript.segments[1].text == "Ертең запись бар ма?"
    assert report.mixed_language is True and report.languages == ["ru", "kk"]
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_groq_call_client_uses_whisper_and_structured_private_report() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/audio/transcriptions"):
            assert b"verbose_json" in request.content
            assert b"whisper-large-v3-turbo" in request.content
            return httpx.Response(200, json={
                "duration": 12.0,
                "segments": [
                    {"start": 0, "end": 4, "text": "Клиника, здравствуйте"},
                    {"start": 4, "end": 8, "text": "Ертең жазылуға бола ма?"},
                ],
            })
        body = json.loads(request.content)
        assert request.url.path.endswith("/chat/completions")
        assert body["model"] == "openai/gpt-oss-20b"
        assert body["response_format"]["type"] == "json_schema"
        scores = body["response_format"]["json_schema"]["schema"]["properties"]["criteria_scores"]
        assert scores["items"]["properties"]["name"]["enum"] == [
            "Приветствие",
            "Запись",
        ]
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": json.dumps(report_payload(), ensure_ascii=False)
                }
            }]
        })

    client = GroqCallIntelligenceClient(
        api_key="test-key",
        base_url="https://api.groq.test/openai/v1",
        transcription_model="whisper-large-v3-turbo",
        analysis_model="openai/gpt-oss-20b",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    transcript = await client.transcribe(
        b"fake-mp3", filename="test.mp3", content_type="audio/mpeg"
    )
    report = await client.analyze(transcript, rule_payload())
    assert transcript.segments[0].speaker == "UNKNOWN"
    assert transcript.segments[1].text == "Ертең жазылуға бола ма?"
    assert report.mixed_language is True
    assert len(requests) == 2


def test_pipeline_defaults_to_groq_for_call_intelligence() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        groq_api_key="groq-test-key",
    )
    pipeline = CallQualityPipeline(SimpleNamespace(), settings)
    assert isinstance(pipeline.client, GroqCallIntelligenceClient)


@pytest.mark.asyncio
async def test_groq_call_client_maps_free_tier_limit_to_retryable_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limit"}})

    client = GroqCallIntelligenceClient(
        api_key="test-key",
        base_url="https://api.groq.test/openai/v1",
        transcription_model="whisper-large-v3-turbo",
        analysis_model="openai/gpt-oss-20b",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CallIntelligenceError) as error:
        await client.transcribe(
            b"fake-mp3", filename="test.mp3", content_type="audio/mpeg"
        )
    assert error.value.code == "TRANSCRIPTION_RATE_LIMIT"
    assert error.value.retryable is True


@pytest.mark.asyncio
async def test_groq_call_client_requires_its_own_api_key() -> None:
    client = GroqCallIntelligenceClient(
        api_key="",
        base_url="https://api.groq.test/openai/v1",
        transcription_model="whisper-large-v3-turbo",
        analysis_model="openai/gpt-oss-20b",
        timeout_seconds=10,
    )
    with pytest.raises(CallIntelligenceError) as error:
        await client.transcribe(
            b"fake-mp3", filename="test.mp3", content_type="audio/mpeg"
        )
    assert error.value.code == "AI_NOT_CONFIGURED"
    assert "GROQ_API_KEY" in str(error.value)


def test_pipeline_recomputes_weighted_score_and_marks_low_confidence_for_review() -> None:
    settings = Settings(_env_file=None, app_env="test")
    pipeline = CallQualityPipeline(
        SimpleNamespace(), settings, loader=SimpleNamespace(), client=SimpleNamespace()
    )
    analysis = SimpleNamespace()
    rules = SimpleNamespace(criteria=[
        {"name": "Приветствие", "weight": 25},
        {"name": "Запись", "weight": 75},
    ])
    report = CallReport.model_validate(report_payload(score=1, confidence=0.5))
    pipeline._validate_and_apply(analysis, report, rules, 12.0)
    assert analysis.score == 95
    assert analysis.status == "needs_review"
    assert analysis.needs_review is True
    assert analysis.criteria_scores[1]["weight"] == 75


def test_call_analysis_table_cannot_store_transcript() -> None:
    assert "transcript" not in CallQualityAnalysis.__table__.columns


@pytest.mark.asyncio
async def test_recording_loader_rejects_private_network_url() -> None:
    loader = RecordingLoader(Settings(_env_file=None, app_env="test"))
    with pytest.raises(CallIntelligenceError) as error:
        await loader.load("https://127.0.0.1/private.mp3")
    assert error.value.code == "RECORDING_URL_FORBIDDEN"


def test_report_rejects_out_of_schema_transcript_field() -> None:
    payload = report_payload()
    payload["transcript"] = "Полный текст не должен сохраняться"
    with pytest.raises(Exception):
        CallReport.model_validate(payload)
