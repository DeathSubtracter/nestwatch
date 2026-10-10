"""Dashboard composition with real analysis and mocked Open Wearables transport."""

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.open_wearables import OpenWearablesClient
from app.config import Settings
from app.dependencies import get_open_wearables_client
from app.main import app
from app.schemas.bp_forecast import BPReviewThresholds
from app.schemas.dashboard import PatientDashboard
from app.services import bp_forecast, dashboard, glucose_forecast


PARAMS = {
    "start_date": "2026-10-01", "end_date": "2026-10-14",
    "reference_start": "2026-10-01", "reference_end": "2026-10-07",
    "recent_start": "2026-10-12", "recent_end": "2026-10-14",
}
METRICS = {
    "blood_glucose": (100, "mg/dL"), "blood_pressure_systolic": (120, "mmHg"),
    "blood_pressure_diastolic": (80, "mmHg"), "resting_heart_rate": (60, "bpm"),
    "heart_rate_variability_sdnn": (50, "ms"), "skin_temperature": (32.1, "degC"),
    "body_temperature": (36.7, "degC"), "weight": (72.5, "kg"),
}
SOURCE = {"provider": "apple", "source": "HealthKit", "device": "Watch7,1", "device_type": "watch"}
TOP_LEVEL_KEYS = {
    "synthetic", "prototype", "validated", "patient", "latest_measurements", "timeline",
    "observed_change", "pattern_status", "glucose_forecast", "bp_forecast", "sleep_summary", "data_quality",
}


def sample(metric, day, **fields):
    value, unit = METRICS[metric]
    return {"timestamp": f"2026-10-{day:02d}T12:00:00Z", "type": metric,
            "value": value, "unit": unit, "source": SOURCE, **fields}


def sleep(day, **fields):
    return {
        "id": f"sleep-{day}", "start_time": f"2026-10-{day:02d}T00:00:00Z",
        "end_time": f"2026-10-{day:02d}T08:00:00Z", "duration_seconds": 28800,
        "sleep_duration_seconds": 25200, "time_in_bed_seconds": 28800,
        "efficiency_percent": 87.5, "is_nap": False, "stages": {"deep_minutes": 90},
        "source": SOURCE, **fields,
    }


def page(records, cursor=None):
    return {"data": records, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}, "metadata": {}}


@pytest.fixture(scope="module")
def forecasts():
    # Exercise the saved synthetic datasets once; never call a real wearable API.
    return glucose_forecast.get_glucose_forecast(), bp_forecast.get_bp_forecast(140, 90)


@pytest.fixture
def upstream(monkeypatch, forecasts):
    settings = Settings(
        _env_file=None, open_wearables_base_url="http://mock-wearables.test",
        open_wearables_api_key="test-key", open_wearables_user_id="test-user",
        bp_review_systolic_threshold=140, bp_review_diastolic_threshold=90,
    )
    monkeypatch.setattr(app.state, "settings", settings)
    data = {
        "samples": [sample(metric, day) for metric in METRICS for day in (5, 6, 7, 12, 13, 14)],
        "sleep": [sleep(day) for day in (5, 6, 7, 12, 13, 14)],
        "failures": {}, "pages": None,
    }
    calls, forecast_calls = [], []

    def handler(request):
        calls.append(request)
        assert request.url.host == "mock-wearables.test"
        assert request.headers["X-Open-Wearables-API-Key"] == "test-key"
        resource = request.url.path.removeprefix("/api/v1/users/test-user/")
        assert resource in ("timeseries", "events/sleep")
        failure = data["failures"].get(resource)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if resource == "timeseries" and data["pages"] is not None:
            return httpx.Response(200, json=data["pages"].pop(0))
        return httpx.Response(200, json=page(data["samples"] if resource == "timeseries" else data["sleep"]))

    async def client_dependency():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield OpenWearablesClient(settings, http)

    def get_glucose():
        forecast_calls.append("glucose")
        return forecasts[0]

    def get_bp(systolic, diastolic):
        forecast_calls.append(("bp", systolic, diastolic))
        return forecasts[1]

    monkeypatch.setitem(app.dependency_overrides, get_open_wearables_client, client_dependency)
    monkeypatch.setattr(dashboard, "get_glucose_forecast", get_glucose)
    monkeypatch.setattr(dashboard, "get_bp_forecast", get_bp)
    return data, calls, settings, forecast_calls


def request_dashboard(params=None):
    with TestClient(app) as client:
        return client.get("/patients/maya/dashboard", params=PARAMS if params is None else params)


def result(params=None):
    response = request_dashboard(params)
    assert response.status_code == 200, response.text
    return response.json()


def test_full_response_has_all_sections_flags_and_latest_provenance(upstream, forecasts):
    _, calls, _, forecast_calls = upstream
    body = result()
    assert set(body) == TOP_LEVEL_KEYS
    assert body["synthetic"] is body["prototype"] is True
    assert body["validated"] is False
    assert body["patient"]["display_name"] == "Maya"
    assert body["patient"]["synthetic"] is True
    assert body["data_quality"]["status"] == "complete"
    assert body["data_quality"]["unavailable_sections"] == {}
    assert body["data_quality"]["missing_measurements"] == body["data_quality"]["stale_measurements"] == []
    assert set(body["latest_measurements"]) == set(METRICS)
    for metric, (value, unit) in METRICS.items():
        row = body["latest_measurements"][metric]
        assert row["metric_type"] == metric
        assert row["metric_definition"]
        assert row["value"] == value
        assert row["unit"] == unit
        assert row["timestamp"] == "2026-10-14T12:00:00Z"
        assert row["status"] == "available"
        assert all(row[key] == expected for key, expected in SOURCE.items())
    assert body["timeline"]["count"] == len(body["timeline"]["entries"])
    assert body["pattern_status"]["status"] == "normal"
    assert len(body["glucose_forecast"]["forecast_points"]) == 288
    assert body["glucose_forecast"] == forecasts[0].model_dump(mode="json")
    assert body["bp_forecast"] == forecasts[1].model_dump(mode="json")
    summary = body["sleep_summary"]
    assert summary["status"] == "available"
    assert summary["session_count"] == 3
    assert summary["window"] == {"start_date": "2026-10-12", "end_date": "2026-10-14"}
    assert summary["latest_session"]["value"]["sleep_duration_seconds"] == 25200
    assert summary["latest_session"]["value"]["efficiency_percent"] == 87.5
    assert summary["latest_session"]["provider"] == "apple"
    assert summary["latest_session"]["details"]["id"] == "sleep-14"
    assert len(calls) == 2  # Shared data, rather than separate fetches per analysis.
    assert "glucose" in forecast_calls and ("bp", 140, 90) in forecast_calls


def test_composed_sections_match_existing_endpoints_exactly(upstream):
    body = result()
    with TestClient(app) as client:
        assert body["patient"] == client.get("/patients/maya").json()
        assert body["timeline"] == client.get("/patients/maya/timeline", params={
            "start_date": PARAMS["start_date"], "end_date": PARAMS["end_date"],
        }).json()
        analysis_params = {key: value for key, value in PARAMS.items() if key not in ("start_date", "end_date")}
        assert body["observed_change"] == client.get("/patients/maya/observed-change", params=analysis_params).json()
        assert body["pattern_status"] == client.get("/patients/maya/pattern-status", params=analysis_params).json()
        assert body["glucose_forecast"] == client.get("/patients/maya/forecast/glucose").json()
        assert body["bp_forecast"] == client.get("/patients/maya/forecast/bp").json()


def test_missing_core_metric_is_explicit_and_analysis_abstains(upstream):
    data, _, _, _ = upstream
    data["samples"] = [row for row in data["samples"] if row["type"] != "blood_glucose"]
    body = result()
    assert body["data_quality"]["status"] == "partial"
    assert body["data_quality"]["missing_measurements"] == ["blood_glucose"]
    row = body["latest_measurements"]["blood_glucose"]
    assert row["status"] == "missing" and row["value"] is row["timestamp"] is None
    assert body["pattern_status"]["status"] == "insufficient_data"
    assert "pattern_status" in body["data_quality"]["unavailable_sections"]
    metric = body["observed_change"]["metrics"][0]
    assert metric["enough_data"] is False and metric["absolute_change"] is None
    assert body["data_quality"]["sections"]["observed_change"]["metric_reasons"]["blood_glucose"] == metric["reasons"]
    assert body["glucose_forecast"] is not None


def test_stale_latest_measurements_remain_visible_and_marked(upstream):
    data, _, _, _ = upstream
    for row in data["samples"]:
        if row["type"] == "weight" and row["timestamp"] >= "2026-10-12":
            row["timestamp"] = "2026-10-09T12:00:00Z"
    body = result()
    row = body["latest_measurements"]["weight"]
    assert row["status"] == "stale" and row["value"] == 72.5
    assert body["data_quality"]["stale_measurements"] == ["weight"]
    assert body["data_quality"]["status"] == "partial"
    assert body["data_quality"]["max_staleness_days"] == 2


def test_empty_wearables_preserve_patient_context_and_forecasts_without_implying_normal(upstream):
    data, _, _, _ = upstream
    data["samples"] = data["sleep"] = []
    body = result()
    assert body["data_quality"]["status"] == "insufficient_data"
    assert set(body["data_quality"]["missing_measurements"]) == set(METRICS)
    assert all(row["status"] == "missing" and row["value"] is None for row in body["latest_measurements"].values())
    assert body["pattern_status"]["status"] == "insufficient_data"
    assert body["observed_change"] is not None
    assert body["sleep_summary"]["status"] == "missing"
    assert body["sleep_summary"]["session_count"] == 0
    assert body["patient"]["display_name"] == "Maya"
    assert body["timeline"]["entries"] and all(row["origin"] == "nestwatch" for row in body["timeline"]["entries"])
    assert body["glucose_forecast"] is not None and body["bp_forecast"] is not None


@pytest.mark.parametrize("section,error", [
    ("glucose_forecast", glucose_forecast.GlucoseForecastError("Synthetic CGM dataset is unavailable or invalid")),
    ("bp_forecast", bp_forecast.BPForecastError("Synthetic BP dataset is unavailable or invalid")),
])
def test_optional_forecast_failure_preserves_all_other_sections(upstream, monkeypatch, section, error):
    def fail(*args):
        raise error

    monkeypatch.setattr(dashboard, f"get_{section}", fail)
    body = result()
    assert body[section] is None
    assert body["data_quality"]["status"] == "partial"
    assert body["data_quality"]["unavailable_sections"] == {section: [str(error)]}
    assert body["data_quality"]["sections"][section]["status"] == "unavailable"
    other = "bp_forecast" if section == "glucose_forecast" else "glucose_forecast"
    assert body[other] is not None
    assert body["timeline"]["entries"]
    assert body["observed_change"] is not None and body["pattern_status"] is not None


def test_insufficient_bp_result_is_retained_with_its_original_flags_and_reasons(upstream, monkeypatch):
    insufficient = bp_forecast.train_and_forecast(
        bp_forecast.BPSeries((), [], []), BPReviewThresholds(systolic_mm_hg=140, diastolic_mm_hg=90),
    )
    monkeypatch.setattr(dashboard, "get_bp_forecast", lambda *args: insufficient)
    body = result()
    assert body["bp_forecast"] == insufficient.model_dump(mode="json")
    assert body["bp_forecast"]["probability"] is None
    assert body["data_quality"]["sections"]["bp_forecast"]["status"] == "insufficient_data"
    assert body["data_quality"]["unavailable_sections"]["bp_forecast"] == ["missing_bp_history"]


def test_sleep_outage_does_not_remove_timeseries_analysis_or_forecasts(upstream):
    data, _, _, _ = upstream
    data["failures"]["events/sleep"] = httpx.Response(500, json={"secret": "upstream private data"})
    body = result()
    assert body["data_quality"]["status"] == "partial"
    assert all(row["status"] == "available" for row in body["latest_measurements"].values())
    assert body["sleep_summary"]["status"] == "unavailable"
    assert body["sleep_summary"]["session_count"] is None
    assert body["sleep_summary"]["latest_session"] is None
    assert body["observed_change"] is not None
    assert body["pattern_status"]["status"] == "watch"
    assert body["pattern_status"]["data_quality"]["coverage"] == "partial"
    assert body["data_quality"]["sections"]["timeline"]["status"] == "partial"
    assert body["data_quality"]["unavailable_sections"]["sleep_summary"] == ["Open Wearables returned HTTP 500"]
    assert "upstream private data" not in str(body)


def test_timeseries_outage_is_distinct_from_empty_data_and_keeps_sleep(upstream):
    data, _, _, _ = upstream
    data["failures"]["timeseries"] = httpx.ConnectError("private connection diagnostic")
    body = result()
    assert body["data_quality"]["status"] == "insufficient_data"
    assert body["data_quality"]["missing_measurements"] == []  # Failure is not evidence of missing values.
    assert all(row["status"] == "unavailable" and row["value"] is None for row in body["latest_measurements"].values())
    assert body["observed_change"] is body["pattern_status"] is None
    assert body["sleep_summary"]["status"] == "available"
    assert any(row["kind"] == "sleep" for row in body["timeline"]["entries"])
    assert body["glucose_forecast"] is not None
    assert "private connection diagnostic" not in str(body)
    for section in ("latest_measurements", "observed_change", "pattern_status"):
        assert body["data_quality"]["unavailable_sections"][section] == ["Open Wearables is unavailable"]


def test_all_optional_sections_can_be_unavailable_without_losing_patient_context(upstream, monkeypatch):
    data, _, _, _ = upstream
    data["failures"] = {resource: httpx.ConnectError("unavailable") for resource in ("timeseries", "events/sleep")}

    def fail_glucose():
        raise glucose_forecast.GlucoseForecastError("Synthetic CGM dataset is unavailable or invalid")

    def fail_bp(*args):
        raise bp_forecast.BPForecastError("Synthetic BP dataset is unavailable or invalid")

    monkeypatch.setattr(dashboard, "get_glucose_forecast", fail_glucose)
    monkeypatch.setattr(dashboard, "get_bp_forecast", fail_bp)
    body = result()
    assert body["data_quality"]["status"] == "insufficient_data"
    assert body["patient"]["display_name"] == "Maya"
    assert body["timeline"]["entries"] and all(row["origin"] == "nestwatch" for row in body["timeline"]["entries"])
    assert body["observed_change"] is body["pattern_status"] is body["glucose_forecast"] is body["bp_forecast"] is None
    assert body["sleep_summary"]["status"] == "unavailable"
    assert set(body["data_quality"]["unavailable_sections"]) == {
        "latest_measurements", "observed_change", "pattern_status", "glucose_forecast", "bp_forecast", "sleep_summary",
    }
    assert set(body) == TOP_LEVEL_KEYS


def test_missing_optional_sleep_is_reported_without_synthesizing_a_summary(upstream):
    data, _, _, _ = upstream
    data["sleep"] = []
    body = result()
    assert body["data_quality"]["status"] == "partial"
    assert body["sleep_summary"]["status"] == "missing"
    assert body["sleep_summary"]["latest_session"] is None
    assert body["sleep_summary"]["session_count"] == 0
    assert body["data_quality"]["unavailable_sections"]["sleep_summary"] == ["missing_recent_sleep_data"]
    assert body["pattern_status"]["status"] == "watch"
    assert body["observed_change"] is not None


@pytest.mark.parametrize("resource", ["timeseries", "events/sleep"])
def test_malformed_resource_is_isolated_using_existing_record_validation(upstream, resource):
    data, _, _, _ = upstream
    if resource == "timeseries":
        data["samples"][0]["value"] = "invalid"
    else:
        data["sleep"][0]["duration_seconds"] = "invalid"
    body = result()
    section = "latest_measurements" if resource == "timeseries" else "sleep_summary"
    assert body["data_quality"]["sections"][section]["status"] == "unavailable"
    assert body["data_quality"]["unavailable_sections"][section] == ["Open Wearables returned an invalid timeline record"]
    assert body["patient"] and body["glucose_forecast"] and body["bp_forecast"]


@pytest.mark.parametrize("section,operation", [
    ("pattern_status", "analyze_pattern"), ("observed_change", "analyze_observed_change"),
    ("glucose_forecast", "get_glucose_forecast"),
])
def test_unexpected_optional_section_errors_are_isolated_and_sanitized(upstream, monkeypatch, section, operation):
    def fail(*args):
        raise RuntimeError("private internal diagnostic")

    monkeypatch.setattr(dashboard, operation, fail)
    body = result()
    assert body[section] is None
    assert body["data_quality"]["unavailable_sections"][section] == ["unexpected_section_failure"]
    assert "private internal diagnostic" not in str(body)
    assert body["patient"] and body["timeline"]["entries"]


def test_range_specific_timeline_rebuilds_context_and_analysis_uses_separate_windows(upstream):
    _, calls, _, _ = upstream
    body = result({**PARAMS, "start_date": "2026-10-13", "end_date": "2026-10-14"})
    assert body["timeline"]["start_date"] == "2026-10-13"
    timestamps = [datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) for row in body["timeline"]["entries"]]
    assert all(timestamp.astimezone(timezone.utc).date().isoformat() in ("2026-10-13", "2026-10-14") for timestamp in timestamps)
    assert {row["metric_type"] for row in body["timeline"]["entries"] if row["kind"] == "context"} >= {
        "pregnancy_stage", "diabetes_context", "treatment_context",
    }
    assert body["observed_change"]["metrics"][0]["reference_sample_count"] == 3
    assert body["pattern_status"]["status"] == "normal"
    assert body["sleep_summary"]["session_count"] == 3
    for call in calls:
        params = call.url.params
        assert params.get("start_time", params.get("start_date")) == "2026-10-01"
        assert params.get("end_time", params.get("end_date")) == "2026-10-14"


def test_latest_values_respect_range_and_select_by_instant_not_string_order(upstream):
    data, _, _, _ = upstream
    data["samples"] += [sample("blood_glucose", 14, timestamp="2026-10-14T08:00:00-07:00", value=107),
                        sample("blood_glucose", 14, timestamp="2026-10-14T16:00:00+02:00", value=109),
                        sample("blood_glucose", 15, value=999)]
    body = result()
    row = body["latest_measurements"]["blood_glucose"]
    assert row["timestamp"] == "2026-10-14T08:00:00-07:00"
    assert row["value"] == 107  # 15:00 UTC is after 14:00 UTC, but before the out-of-range sample.
    historical = result({**PARAMS, "start_date": "2026-10-05", "end_date": "2026-10-07"})
    assert historical["latest_measurements"]["blood_glucose"]["timestamp"] == "2026-10-07T12:00:00Z"
    assert historical["latest_measurements"]["blood_glucose"]["status"] == "available"


def test_sleep_summary_uses_recent_utc_window_and_preserves_nap_status(upstream):
    data, _, _, _ = upstream
    data["sleep"] += [sleep(14, end_time="2026-10-15T01:00:00+02:00", is_nap=True)]
    body = result()
    summary = body["sleep_summary"]
    assert summary["session_count"] == 4
    assert summary["latest_session"]["timestamp"] == "2026-10-15T01:00:00+02:00"
    assert summary["latest_session"]["value"]["is_nap"] is True
    assert body["pattern_status"]["status"] == "normal"  # Existing detector still excludes naps.


def test_stale_sleep_summary_retains_values_and_marks_insufficiency(upstream):
    data, _, _, _ = upstream
    data["sleep"] = [sleep(5), sleep(6), sleep(7), sleep(8)]
    body = result({**PARAMS, "recent_start": "2026-10-08"})
    assert body["sleep_summary"]["status"] == "stale"
    assert body["sleep_summary"]["latest_session"]["value"]["sleep_duration_seconds"] == 25200
    assert body["data_quality"]["sections"]["sleep_summary"]["status"] == "insufficient_data"
    assert body["data_quality"]["status"] == "partial"


def test_forecasts_keep_existing_origins_and_use_configured_bp_thresholds(upstream, forecasts):
    _, _, settings, forecast_calls = upstream
    settings.bp_review_systolic_threshold = 145
    settings.bp_review_diastolic_threshold = 95
    body = result({**PARAMS, "end_date": "2026-10-07"})
    assert ("bp", 145, 95) in forecast_calls
    assert body["glucose_forecast"]["forecast_origin"] == forecasts[0].model_dump(mode="json")["forecast_origin"]
    assert body["bp_forecast"]["forecast_origin"] == forecasts[1].model_dump(mode="json")["forecast_origin"]


def test_all_cursor_pages_are_shared_across_sections(upstream):
    data, calls, _, _ = upstream
    data["pages"] = [page(data["samples"][:20], "page-two"), page(data["samples"][20:])]
    body = result()
    assert body["data_quality"]["status"] == "complete"
    assert len(calls) == 3
    timeseries_calls = [call for call in calls if call.url.path.endswith("/timeseries")]
    assert timeseries_calls[1].url.params["cursor"] == "page-two"


@pytest.mark.parametrize("missing_section", [None, "glucose_forecast", "bp_forecast"])
def test_response_schema_is_stable_in_full_and_partial_responses(upstream, monkeypatch, missing_section):
    if missing_section:
        def fail(*args):
            raise RuntimeError("unavailable")

        monkeypatch.setattr(dashboard, f"get_{missing_section}", fail)
    body = result()
    assert set(body) == TOP_LEVEL_KEYS
    assert PatientDashboard.model_validate(body).model_dump(mode="json") == body
    assert set(body["latest_measurements"]) == set(METRICS)
    assert set(body["latest_measurements"]["blood_glucose"]) == {
        "metric_type", "metric_definition", "status", "value", "unit", "timestamp",
        "provider", "source", "device", "device_type", "reasons",
    }
    assert set(body["data_quality"]["sections"]) == TOP_LEVEL_KEYS - {
        "synthetic", "prototype", "validated", "data_quality",
    }
    if missing_section:
        assert body[missing_section] is None


@pytest.mark.parametrize("params", [
    {}, *[{key: value for key, value in PARAMS.items() if key != missing} for missing in PARAMS],
    {**PARAMS, "start_date": "invalid"}, {**PARAMS, "start_date": "2026-10-15"},
    {**PARAMS, "reference_start": "2026-10-08"},
    {**PARAMS, "recent_start": "2026-10-07"}, {**PARAMS, "recent_end": "2026-10-11"},
])
def test_invalid_or_missing_dates_return_422_without_service_calls(upstream, params):
    _, calls, _, forecast_calls = upstream
    assert request_dashboard(params).status_code == 422
    assert calls == forecast_calls == []
