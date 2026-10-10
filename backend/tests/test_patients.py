from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.open_wearables import OpenWearablesClient
from app.config import Settings
from app.dependencies import get_open_wearables_client
from app.main import app

METRICS = [
    "blood_glucose", "blood_pressure_systolic", "blood_pressure_diastolic",
    "heart_rate", "resting_heart_rate", "heart_rate_variability_sdnn",
    "skin_temperature", "body_temperature", "weight",
]
SOURCE = {
    "provider": "apple", "source": "HealthKit", "device": "Watch7,1",
    "device_type": "watch", "device_name": "Apple Watch",
}


def sample(metric="blood_glucose", timestamp="2026-10-02T09:00:00Z", **fields):
    return {
        "timestamp": timestamp, "type": metric, "value": 105.5,
        "unit": "mg/dL", "source": SOURCE, "zone_offset": "-07:00", **fields,
    }


def sleep_session(**fields):
    return {
        "id": "sleep-1", "start_time": "2026-10-02T22:00:00Z",
        "end_time": "2026-10-03T06:00:00Z", "source": SOURCE,
        "duration_seconds": 28800, "sleep_duration_seconds": 27000,
        "time_in_bed_seconds": 28800, "efficiency_percent": 93.75,
        "stages": {"deep_minutes": 90}, "is_nap": False,
        "sleep_stage_intervals": [{"stage": "deep", "start_time": "2026-10-03T00:00:00Z"}],
        **fields,
    }


def page(records, cursor=None):
    return {
        "data": records,
        "pagination": {"has_more": cursor is not None, "next_cursor": cursor},
        "metadata": {},
    }


@pytest.fixture
def upstream(monkeypatch):
    calls = []
    responses = {"timeseries": page([]), "events/sleep": page([])}
    settings = Settings(
        _env_file=None,
        open_wearables_base_url="http://mock-wearables.test",
        open_wearables_api_key="test-key",
        open_wearables_user_id="test-user",
        nestwatch_patient_id="maya",
    )

    def handler(request):
        calls.append(request)
        assert request.url.host == "mock-wearables.test"
        assert request.headers["X-Open-Wearables-API-Key"] == "test-key"
        resource = request.url.path.removeprefix("/api/v1/users/test-user/")
        assert resource in responses
        if resource == "timeseries":
            assert request.url.params.get_list("types") == METRICS
        result = responses[resource]
        if isinstance(result, list):
            result = result.pop(0)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    async def client_dependency():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield OpenWearablesClient(settings, http)

    monkeypatch.setitem(app.dependency_overrides, get_open_wearables_client, client_dependency)
    return responses, calls


def timeline(start="2026-10-01", end="2026-10-07"):
    with TestClient(app) as client:
        return client.get("/patients/maya/timeline", params={"start_date": start, "end_date": end})


def test_profile_is_local_and_synthetic(monkeypatch):
    async def no_http(*args, **kwargs):
        pytest.fail("The profile must not contact Open Wearables")

    monkeypatch.setattr(httpx.AsyncClient, "get", no_http)
    with TestClient(app) as client:
        response = client.get("/patients/maya")
    assert response.status_code == 200
    patient = response.json()
    assert patient["patient_id"] == "maya"
    assert patient["display_name"] == "Maya"
    assert patient["synthetic"] is True
    assert patient["gestational_age"] == {"weeks": 10, "days": 0, "as_of_date": "2026-10-01"}
    assert patient["glp1_last_dose_date"] == "2026-09-15"
    assert patient["medication_transition_date"] == "2026-09-22"
    assert patient["diabetes"]["type"] == "type_2"
    assert patient["current_treatment_text"]
    assert {symptom["name"] for symptom in patient["symptoms"]} == {"nausea", "fatigue"}


def test_unified_timeline_preserves_all_metrics_and_sleep(upstream):
    responses, calls = upstream
    units = ["mg/dL", "mmHg", "mmHg", "bpm", "bpm", "ms", "degC", "degC", "kg"]
    samples = [sample(metric, value=index, unit=unit) for index, (metric, unit) in enumerate(zip(METRICS, units))]
    session = sleep_session()
    responses["timeseries"] = page(samples)
    responses["events/sleep"] = page([session])
    response = timeline()
    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == "maya"
    assert body["synthetic"] is True
    assert body["timezone"] == "UTC"
    assert body["start_date"] == "2026-10-01"
    assert body["end_date"] == "2026-10-07"
    assert body["patient_context"]["display_name"] == "Maya"
    entries = body["entries"]
    assert body["count"] == len(entries) == 15
    assert len(calls) == 2
    timestamps = [datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")) for entry in entries]
    assert timestamps == sorted(timestamps)
    measurements = [entry for entry in entries if entry["kind"] == "measurement"]
    assert [entry["metric_type"] for entry in measurements] == METRICS
    for entry, original in zip(measurements, samples):
        assert entry["timestamp"] == original["timestamp"]
        assert entry["metric_definition"]
        assert entry["value"] == original["value"]
        assert entry["unit"] == original["unit"]
        assert entry["origin"] == "open_wearables"
        for field in ("provider", "source", "device", "device_type"):
            assert entry[field] == SOURCE[field]
        assert entry["details"] == original
    sleep = next(entry for entry in entries if entry["kind"] == "sleep")
    assert sleep["timestamp"] == session["end_time"]
    assert sleep["metric_type"] == "sleep_summary"
    assert sleep["value"]["sleep_duration_seconds"] == 27000
    assert sleep["value"]["stages"] == {"deep_minutes": 90}
    assert sleep["details"] == session
    assert sleep["device"] == SOURCE["device"]
    owned = [entry for entry in entries if entry["origin"] == "nestwatch"]
    assert {entry["metric_type"] for entry in owned} == {
        "pregnancy_stage", "diabetes_context", "treatment_context", "symptom"
    }
    assert all(entry["details"]["synthetic"] is True for entry in owned)


def test_pagination_is_combined_in_timeline(upstream):
    responses, calls = upstream
    responses["timeseries"] = [page([sample(value=1)], "next"), page([sample(value=2)])]
    responses["events/sleep"] = [page([sleep_session(id="one")], "sleep-next"), page([sleep_session(id="two")])]
    body = timeline().json()
    devices = [entry for entry in body["entries"] if entry["origin"] == "open_wearables"]
    assert [entry["value"] for entry in devices if entry["kind"] == "measurement"] == [1, 2]
    assert [entry["details"]["id"] for entry in devices if entry["kind"] == "sleep"] == ["one", "two"]
    assert len(calls) == 4
    assert calls[1].url.params["cursor"] == "next"
    assert calls[3].url.params["cursor"] == "sleep-next"


def test_dated_medication_and_context_snapshots(upstream):
    response = timeline("2026-09-15", "2026-09-22")
    assert response.status_code == 200
    entries = response.json()["entries"]
    by_metric = {entry["metric_type"]: entry for entry in entries}
    assert by_metric["glp1_last_dose"]["timestamp"] == "2026-09-15T00:00:00Z"
    assert by_metric["glp1_last_dose"]["details"]["date_only"] is True
    assert by_metric["medication_transition"]["timestamp"] == "2026-09-22T00:00:00Z"
    assert by_metric["treatment_context"]["timestamp"] == "2026-09-22T00:00:00Z"
    assert by_metric["pregnancy_stage"]["value"] == {"weeks": 7, "days": 5, "stage": "first_trimester"}
    assert by_metric["pregnancy_stage"]["details"]["snapshot"] is True
    assert "symptom" not in by_metric


def test_no_future_treatment_or_medication_is_backdated(upstream):
    body = timeline("2026-09-01", "2026-09-07").json()
    assert {entry["metric_type"] for entry in body["entries"]} == {"pregnancy_stage", "diabetes_context"}


@pytest.mark.parametrize("day,weeks,days,stage", [
    ("2026-10-01", 10, 0, "first_trimester"),
    ("2026-10-07", 10, 6, "first_trimester"),
    ("2026-10-29", 14, 0, "second_trimester"),
    ("2027-02-04", 28, 0, "third_trimester"),
])
def test_pregnancy_snapshot_is_anchored_to_fixture(upstream, day, weeks, days, stage):
    body = timeline(day, day).json()
    pregnancy = next(entry for entry in body["entries"] if entry["metric_type"] == "pregnancy_stage")
    assert pregnancy["value"] == {"weeks": weeks, "days": days, "stage": stage}


def test_range_filters_all_entries_and_sorts_offsets_by_instant(upstream):
    responses, _ = upstream
    first = sample(timestamp="2026-10-02T23:00:00-07:00", value=1)
    second = sample(timestamp="2026-10-03T07:30:00Z", value=2)
    end = sample(timestamp="2026-10-03T23:59:59.999999Z", value=3)
    responses["timeseries"] = page([
        second, first, end,
        sample(timestamp="2026-10-03T00:30:00+02:00", value=4),
        sample(timestamp="2026-10-04T00:00:00Z", value=5),
        sample("steps", value=6),
    ])
    responses["events/sleep"] = page([sleep_session(), sleep_session(end_time="2026-10-04T00:00:00Z")])
    body = timeline("2026-10-03", "2026-10-03").json()
    measurements = [entry for entry in body["entries"] if entry["kind"] == "measurement"]
    assert [entry["value"] for entry in measurements] == [1, 2, 3]
    assert measurements[0]["timestamp"] == first["timestamp"]
    assert len([entry for entry in body["entries"] if entry["kind"] == "sleep"]) == 1
    assert not any(entry["kind"] in ("symptom", "medication") for entry in body["entries"])


def test_missing_optional_device_metadata_is_not_invented(upstream):
    responses, _ = upstream
    responses["timeseries"] = page([sample(source=None)])
    body = timeline().json()
    measurement = next(entry for entry in body["entries"] if entry["kind"] == "measurement")
    assert all(measurement[field] is None for field in ("provider", "source", "device", "device_type"))
    assert measurement["details"]["source"] is None


def test_empty_wearable_result_retains_patient_context(upstream):
    body = timeline().json()
    assert body["count"] == 5
    assert all(entry["origin"] == "nestwatch" for entry in body["entries"])
    assert len([entry for entry in body["entries"] if entry["kind"] == "symptom"]) == 2


@pytest.mark.parametrize("resource", ["timeseries", "events/sleep"])
@pytest.mark.parametrize("failure,status", [
    (httpx.ConnectError("private information"), 503),
    (httpx.ReadTimeout("private information"), 504),
    (httpx.Response(401, json={"detail": "private information"}), 502),
])
def test_timeline_upstream_failure_is_not_partial_success(upstream, resource, failure, status):
    responses, _ = upstream
    responses["timeseries"] = page([sample()])
    responses[resource] = failure
    response = timeline()
    assert response.status_code == status
    assert "private information" not in response.text
    assert "entries" not in response.json()


@pytest.mark.parametrize("params", [
    {}, {"start_date": "bad", "end_date": "2026-10-07"},
    {"start_date": "2026-10-07", "end_date": "2026-10-01"},
])
def test_invalid_dates_do_not_contact_upstream(upstream, params):
    _, calls = upstream
    with TestClient(app) as client:
        response = client.get("/patients/maya/timeline", params=params)
    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("record", [
    sample(timestamp="invalid"), sample(timestamp=123), sample(value="not numeric"),
    sample(unit=None), sample(source="invalid"), {"type": "blood_glucose"},
])
def test_malformed_timeseries_fails_cleanly(upstream, record):
    responses, _ = upstream
    responses["timeseries"] = page([record])
    response = timeline()
    assert response.status_code == 502
    assert response.json() == {"detail": "Open Wearables returned an invalid timeline record"}


def test_malformed_sleep_fails_cleanly(upstream):
    responses, _ = upstream
    responses["events/sleep"] = page([sleep_session(duration_seconds=None)])
    assert timeline().status_code == 502


def test_only_maya_is_exposed():
    with TestClient(app) as client:
        assert client.get("/patients/another-patient").status_code == 404
