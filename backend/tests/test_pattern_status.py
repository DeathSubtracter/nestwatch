"""Exercise the real timeline/client path against mocked Open Wearables only."""

from math import sqrt

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.clients.open_wearables import OpenWearablesClient
from app.config import Settings
from app.dependencies import get_open_wearables_client
from app.main import app


WINDOWS = {
    "reference_start": "2026-10-01", "reference_end": "2026-10-07",
    "recent_start": "2026-10-12", "recent_end": "2026-10-14",
}
BASELINES = {
    "blood_glucose": (100, "mg/dL"),
    "blood_pressure_systolic": (120, "mmHg"),
    "blood_pressure_diastolic": (80, "mmHg"),
    "resting_heart_rate": (60, "bpm"),
    "heart_rate_variability_sdnn": (50, "ms"),
}
SOURCE = {"provider": "apple", "source": "HealthKit", "device": "Watch7,1", "device_type": "watch"}


def sample(metric, value, day):
    return {
        "timestamp": f"2026-10-{day:02d}T12:00:00Z", "type": metric,
        "value": value, "unit": BASELINES.get(metric, (None, "degC"))[1], "source": SOURCE,
    }


def sleep(day, duration=25200, efficiency=90, **fields):
    return {
        "start_time": f"2026-10-{day:02d}T00:00:00Z",
        "end_time": f"2026-10-{day:02d}T08:00:00Z",
        "duration_seconds": 28800, "sleep_duration_seconds": duration,
        "efficiency_percent": efficiency, "source": SOURCE, "is_nap": False, **fields,
    }


def page(records, cursor=None):
    return {"data": records, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}, "metadata": {}}


@pytest.fixture
def upstream(monkeypatch):
    settings = Settings(
        _env_file=None, open_wearables_base_url="http://mock-wearables.test",
        open_wearables_api_key="test-key", open_wearables_user_id="test-user",
    )
    monkeypatch.setattr(app.state, "settings", settings)
    data = {
        "samples": [sample(metric, baseline, day) for metric, (baseline, _) in BASELINES.items()
                    for day in (5, 6, 7, 12, 13, 14)],
        "sleep": [sleep(day) for day in (5, 6, 7, 12, 13, 14)],
        "pages": None, "failure": None,
    }
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "mock-wearables.test"
        assert request.headers["X-Open-Wearables-API-Key"] == "test-key"
        resource = request.url.path.removeprefix("/api/v1/users/test-user/")
        assert resource in ("timeseries", "events/sleep")
        if isinstance(data["failure"], Exception):
            raise data["failure"]
        if data["failure"] is not None:
            return data["failure"]
        if resource == "timeseries":
            if data["pages"] is not None:
                return httpx.Response(200, json=data["pages"].pop(0))
            return httpx.Response(200, json=page(data["samples"]))
        return httpx.Response(200, json=page(data["sleep"]))

    async def dependency():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield OpenWearablesClient(settings, http)

    monkeypatch.setitem(app.dependency_overrides, get_open_wearables_client, dependency)
    return data, calls, settings


def request_status(params=None):
    with TestClient(app) as client:
        return client.get("/patients/maya/pattern-status", params=WINDOWS if params is None else params)


def status(params=None):
    response = request_status(params)
    assert response.status_code == 200, response.text
    return response.json()


def signal(body, metric):
    return next(item for item in body["signals"] if item["metric_type"] == metric)


def change(data, *metrics, fraction=0.06):
    for item in data["samples"]:
        if item["type"] in metrics and item["timestamp"] >= "2026-10-12":
            item["value"] *= 1 + fraction


def test_stable_multisignal_case_is_normal_and_has_explicit_schema(upstream):
    _, calls, _ = upstream
    body = status()
    assert body["status"] == "normal"
    assert body["patient_id"] == "maya"
    assert body["validated"] is False
    assert body["prototype"] is True
    assert body["synthetic"] is True
    assert body["timezone"] == "UTC"
    assert body["data_quality"]["coverage"] == "complete"
    assert body["data_quality"]["missing_required_signals"] == []
    assert body["contributing_signals"] == []
    assert len(body["signals"]) == len(body["non_contributing_signals"]) == 9
    assert body["reasons"] == ["no_qualifying_directional_changes"]
    assert body["reference_window"] == {"start_date": "2026-10-01", "end_date": "2026-10-07"}
    assert body["recent_window"] == {"start_date": "2026-10-12", "end_date": "2026-10-14"}
    for item in body["signals"][:7]:
        assert item["usable"] is True
        assert item["changed"] is False
        assert item["normalized_change"] == item["contribution"] == 0
        assert item["comparison"]["reference_sample_count"] == item["comparison"]["recent_sample_count"] == 3
        assert item["persistence"]["meets_persistence"] is False
    assert len(calls) == 2
    assert calls[0].url.params["start_time"] == "2026-10-01"
    assert calls[0].url.params["end_time"] == "2026-10-14"
    assert set(BASELINES) <= set(calls[0].url.params.get_list("types"))


def test_one_moderate_persistent_signal_never_gets_highest_status(upstream):
    data, _, _ = upstream
    change(data, "blood_glucose")
    body = status()
    assert body["status"] == "watch"
    assert body["contributing_signals"] == ["blood_glucose"]
    glucose = signal(body, "blood_glucose")
    assert glucose["normalization_scale"] == 5
    assert glucose["normalized_change"] == glucose["contribution"] == pytest.approx(1.2)
    assert glucose["persistence"]["latest_consecutive_days"] == 3
    assert glucose["persistence"]["meets_persistence"] is True
    assert body["latest_concurrent_days"] == 0


def test_three_moderate_persistent_groups_change_to_review(upstream):
    data, _, _ = upstream
    metrics = ["blood_glucose", "blood_pressure_systolic", "resting_heart_rate"]
    change(data, *metrics)
    body = status()
    assert body["status"] == "change_to_review"
    assert body["contributing_signals"] == metrics
    assert body["latest_concurrent_days"] == body["longest_concurrent_days"] == 3
    assert body["reasons"] == ["multiple_groups_changed_together_persistently"]
    assert all(len(day["groups"]) == 3 for day in body["concurrent_days"])
    # These rules do not depend on a hard BP review value.
    assert signal(body, "blood_pressure_systolic")["comparison"]["recent_mean"] == pytest.approx(127.2)


def test_two_groups_are_an_intermediate_watch_case(upstream):
    data, _, _ = upstream
    change(data, "blood_glucose", "resting_heart_rate")
    assert status()["status"] == "watch"


def test_duplicate_bp_and_sleep_signals_do_not_inflate_group_count(upstream):
    data, _, _ = upstream
    change(data, "blood_pressure_systolic", "blood_pressure_diastolic")
    for item in data["sleep"]:
        if item["end_time"] >= "2026-10-12":
            item["sleep_duration_seconds"] *= 0.94
            item["efficiency_percent"] *= 0.94
    body = status()
    assert len(body["contributing_signals"]) == 4
    assert body["status"] == "watch"
    assert all(day["groups"] == ["blood_pressure", "sleep"] for day in body["concurrent_days"])


@pytest.mark.parametrize("metric", list(BASELINES))
def test_missing_required_signal_abstains_even_when_other_signals_change(upstream, metric):
    data, _, _ = upstream
    change(data, *BASELINES)
    data["samples"] = [item for item in data["samples"] if item["type"] != metric]
    body = status()
    assert body["status"] == "insufficient_data"
    assert body["data_quality"]["coverage"] == "insufficient"
    assert body["data_quality"]["missing_required_signals"] == [metric]
    missing = signal(body, metric)
    assert missing["usable"] is False
    assert missing["changed"] is None
    assert missing["normalized_change"] is None
    assert missing["contribution"] is None
    assert missing["contributing"] is False
    assert "missing_reference_data" in missing["reasons"]
    assert "required_signals_unavailable" in body["reasons"]


def test_missing_optional_sleep_reduces_coverage_and_never_implies_normal(upstream):
    data, _, _ = upstream
    data["sleep"] = []
    body = status()
    assert body["status"] == "watch"
    assert body["data_quality"]["coverage"] == "partial"
    assert body["data_quality"]["unavailable_primary_signals"] == ["sleep_duration", "sleep_efficiency"]
    assert body["data_quality"]["missing_required_signals"] == []
    assert signal(body, "sleep_duration")["contribution"] is None


@pytest.mark.parametrize("fraction,contributes", [(-0.06, True), (0.06, False)])
def test_hrv_decreases_contribute_but_increases_do_not(upstream, fraction, contributes):
    data, _, _ = upstream
    change(data, "heart_rate_variability_sdnn", fraction=fraction)
    body = status()
    hrv = signal(body, "heart_rate_variability_sdnn")
    assert hrv["direction"] == "decrease"
    assert hrv["normalized_change"] == pytest.approx(fraction / 0.05)
    assert hrv["directional_normalized_change"] == pytest.approx(-fraction / 0.05)
    assert hrv["contributing"] is contributes
    assert body["status"] == ("watch" if contributes else "normal")


@pytest.mark.parametrize("field,metric,unit", [
    ("sleep_duration_seconds", "sleep_duration", "s"),
    ("efficiency_percent", "sleep_efficiency", "%"),
])
def test_worsening_sleep_contributes_with_source_reported_values(upstream, field, metric, unit):
    data, _, _ = upstream
    change(data, "blood_glucose", "resting_heart_rate")
    for item in data["sleep"]:
        if item["end_time"] >= "2026-10-12":
            item[field] *= 0.94
    body = status()
    item = signal(body, metric)
    assert item["direction"] == "decrease"
    assert item["directional_normalized_change"] == pytest.approx(1.2)
    assert item["comparison"]["unit"] == unit
    assert item["comparison"]["reference_provenance"] == [{**SOURCE, "sample_count": 3}]
    assert item["persistence"]["meets_persistence"] is True
    assert body["status"] == "change_to_review"


def test_no_sleep_duration_is_inferred_from_session_length_and_naps_do_not_vote(upstream):
    data, _, _ = upstream
    for item in data["sleep"]:
        item["sleep_duration_seconds"] = None
    data["sleep"] += [sleep(day, duration=100, efficiency=1, is_nap=True) for day in (12, 13, 14)]
    body = status()
    assert body["status"] == "watch"
    assert signal(body, "sleep_duration")["comparison"]["recent_sample_count"] == 0
    assert signal(body, "sleep_efficiency")["comparison"]["recent_mean"] == 90
    assert body["data_quality"]["rejected_sleep_values"] == 6


@pytest.mark.parametrize("value", [None, True, "90", -1, 101])
def test_invalid_sleep_efficiency_is_excluded_and_reported(upstream, value):
    data, _, _ = upstream
    data["sleep"][-1]["efficiency_percent"] = value
    body = status()
    item = signal(body, "sleep_efficiency")
    assert body["status"] == "watch"
    assert body["data_quality"]["coverage"] == "partial"
    assert item["rejected_recent_samples"] == 1
    assert item["comparison"]["recent_sample_count"] == 2
    assert item["contribution"] is None
    assert "missing_or_invalid_sleep_values_excluded" in item["reasons"]


def test_enough_raw_samples_on_one_day_does_not_establish_persistence(upstream):
    data, _, _ = upstream
    change(data, "blood_glucose")
    for item in data["samples"]:
        if item["type"] == "blood_glucose" and item["timestamp"] >= "2026-10-12":
            item["timestamp"] = "2026-10-14T12:00:00Z"
    body = status()
    item = signal(body, "blood_glucose")
    assert item["comparison"]["enough_data"] is True
    assert item["usable"] is False
    assert "too_few_recent_days" in item["reasons"]
    assert body["status"] == "insufficient_data"


def test_two_changed_days_do_not_establish_persistence(upstream):
    data, _, _ = upstream
    change(data, "blood_glucose", fraction=0.09)
    for item in data["samples"]:
        if item["type"] == "blood_glucose" and item["timestamp"].startswith("2026-10-12"):
            item["value"] = 100
    body = status()
    item = signal(body, "blood_glucose")
    assert item["changed"] is True
    assert item["contributing"] is False
    assert item["contribution"] == 0
    assert item["persistence"]["latest_consecutive_days"] == 2
    assert "change_not_persistent_at_window_end" in item["reasons"]
    assert body["status"] == "watch"


def test_a_stable_day_after_a_changed_run_ends_current_persistence(upstream):
    data, _, _ = upstream
    data["samples"] = [item for item in data["samples"] if item["type"] != "blood_glucose"]
    data["samples"] += [sample("blood_glucose", 100, day) for day in (5, 6, 7, 14)]
    data["samples"] += [sample("blood_glucose", 110, day) for day in (11, 12, 13)]
    body = status({**WINDOWS, "recent_start": "2026-10-11"})
    item = signal(body, "blood_glucose")
    assert item["changed"] is True
    assert item["persistence"]["longest_consecutive_days"] == 3
    assert item["persistence"]["latest_consecutive_days"] == 0
    assert item["contributing"] is False
    assert body["status"] == "watch"


def test_gaps_break_persistence(upstream):
    data, _, _ = upstream
    change(data, "blood_glucose")
    for item in data["samples"]:
        if item["type"] == "blood_glucose" and item["timestamp"].startswith("2026-10-12"):
            item["timestamp"] = "2026-10-10T12:00:00Z"
    body = status({**WINDOWS, "recent_start": "2026-10-10"})
    item = signal(body, "blood_glucose")
    assert item["changed"] is True
    assert item["persistence"]["latest_consecutive_days"] == 2
    assert item["contributing"] is False
    assert body["status"] == "watch"


def test_individually_persistent_changes_need_three_concurrent_days(upstream):
    data, _, _ = upstream
    glucose, bp, hr = "blood_glucose", "blood_pressure_systolic", "resting_heart_rate"
    data["samples"] = [item for item in data["samples"] if item["type"] not in (glucose, bp, hr)]
    for metric, days in ((glucose, (10, 11, 12)), (bp, (11, 12, 13)), (hr, (12, 13, 14))):
        baseline = BASELINES[metric][0]
        data["samples"] += [sample(metric, baseline, day) for day in (5, 6, 7)]
        data["samples"] += [sample(metric, baseline * 1.06, day) for day in days]
    body = status({**WINDOWS, "recent_start": "2026-10-10"})
    assert body["contributing_signals"] == [glucose, bp, hr]
    assert body["longest_concurrent_days"] == 1
    assert body["latest_concurrent_days"] == 0
    assert body["status"] == "watch"


def test_stale_data_never_counts_as_stable(upstream):
    data, _, _ = upstream
    for item in data["samples"]:
        if item["type"] == "blood_glucose" and item["timestamp"] >= "2026-10-12":
            day = int(item["timestamp"][8:10]) - 4
            item["timestamp"] = f"2026-10-{day:02d}T12:00:00Z"
    body = status({**WINDOWS, "recent_start": "2026-10-08"})
    assert body["status"] == "insufficient_data"
    assert "stale_recent_data" in signal(body, "blood_glucose")["reasons"]


@pytest.mark.parametrize("difference", ["device", "unit"])
def test_source_changes_and_unit_changes_abstain_instead_of_comparing(upstream, difference):
    data, _, _ = upstream
    for item in data["samples"]:
        if item["type"] == "blood_glucose" and item["timestamp"] >= "2026-10-12":
            if difference == "device":
                item["source"] = {**SOURCE, "device": "different-device"}
            else:
                item["unit"] = "mmol/L"
    body = status()
    item = signal(body, "blood_glucose")
    assert body["status"] == "insufficient_data"
    assert item["contribution"] is None
    assert ("source_or_device_changed" if difference == "device" else "incompatible_units") in item["reasons"]


def test_unknown_provider_is_visible_and_reduces_coverage(upstream):
    data, _, _ = upstream
    for item in data["samples"]:
        if item["type"] == "blood_glucose":
            item["source"] = None
    body = status()
    assert body["status"] == "watch"
    assert body["data_quality"]["coverage"] == "partial"
    item = signal(body, "blood_glucose")
    assert item["usable"] is True
    assert "unknown_provider_provenance" in item["reasons"]
    assert item["comparison"]["reference_provenance"][0]["provider"] is None


def test_normalization_uses_reference_variability_when_larger_than_floor(upstream):
    data, _, _ = upstream
    reference_values = iter((90, 100, 110))
    for item in data["samples"]:
        if item["type"] == "blood_glucose":
            item["value"] = next(reference_values) if item["timestamp"] < "2026-10-12" else 110
    item = signal(status(), "blood_glucose")
    expected_std = sqrt(200 / 3)
    assert item["reference_std"] == item["normalization_scale"] == pytest.approx(expected_std)
    assert item["normalized_change"] == pytest.approx(10 / expected_std)


def test_zero_normalization_scale_is_explicitly_unavailable(upstream):
    data, _, _ = upstream
    for item in data["samples"]:
        if item["type"] == "blood_glucose":
            item["value"] = 0
    body = status()
    assert body["status"] == "insufficient_data"
    item = signal(body, "blood_glucose")
    assert item["normalized_change"] is None
    assert "zero_or_invalid_normalization_scale" in item["reasons"]


def test_temperature_is_context_only_and_uses_variability_not_percent_floor(upstream):
    data, _, _ = upstream
    for metric in ("skin_temperature", "body_temperature"):
        data["samples"] += [sample(metric, value, day) for value, day in zip((36, 36.1, 36.2, 36.4, 36.4, 36.4), (5, 6, 7, 12, 13, 14))]
    body = status()
    assert body["status"] == "normal"
    for metric in ("skin_temperature", "body_temperature"):
        item = signal(body, metric)
        assert item["normalization_scale"] == item["reference_std"]
        assert item["changed"] is True
        assert item["role"] == "context"
        assert item["contributing"] is False
        assert item["contribution"] == 0
        assert "context_only_not_used_for_escalation" in item["reasons"]


def test_rules_are_configurable_and_do_not_read_bp_forecast_thresholds(upstream):
    data, _, settings = upstream
    change(data, "blood_glucose", "blood_pressure_systolic", "resting_heart_rate")
    original = status()
    settings.bp_review_systolic_threshold = 500
    settings.bp_review_diastolic_threshold = 500
    assert status() == original
    settings.pattern_normalized_change_threshold = 2
    body = status()
    assert body["status"] == "normal"
    assert body["policy"]["normalized_change_threshold"] == 2


def test_custom_required_sleep_signal_abstains_when_sleep_is_missing(upstream):
    data, _, settings = upstream
    data["sleep"] = []
    settings.pattern_required_signals = [*BASELINES, "sleep_duration"]
    body = status()
    assert body["status"] == "insufficient_data"
    assert body["data_quality"]["missing_required_signals"] == ["sleep_duration"]


def test_minimum_group_coverage_prevents_normal_when_required_list_is_relaxed(upstream):
    data, _, settings = upstream
    settings.pattern_required_signals = ["blood_glucose"]
    data["samples"] = [item for item in data["samples"] if item["type"] == "blood_glucose"]
    data["sleep"] = []
    body = status()
    assert body["status"] == "insufficient_data"
    assert "too_few_available_signal_groups" in body["reasons"]
    assert body["data_quality"]["available_groups"] == ["glucose"]


def test_minimum_daily_sample_requirement_prevents_sparse_contributions(upstream):
    data, _, settings = upstream
    settings.pattern_min_samples_per_day = 2
    change(data, "blood_glucose")
    body = status()
    item = signal(body, "blood_glucose")
    assert item["changed"] is True
    assert item["contributing"] is False
    assert item["persistence"]["latest_consecutive_days"] == 0
    assert all("too_few_recent_samples" in day["reasons"] for day in item["persistence"]["daily_changes"])
    assert body["status"] == "watch"


@pytest.mark.parametrize("field,value", [
    ("pattern_normalized_change_threshold", 0), ("pattern_normalized_change_threshold", float("nan")),
    ("pattern_relative_scale_floor", 0), ("pattern_relative_scale_floor", 1.1),
    ("pattern_min_days_per_window", 0), ("pattern_min_samples_per_day", 0),
    ("pattern_persistence_days", 1), ("pattern_review_min_groups", 1),
    ("pattern_min_available_groups", 6), ("pattern_required_signals", []),
    ("pattern_required_signals", ["weight"]),
])
def test_invalid_engineering_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_required_signals_can_be_read_as_json_from_environment(monkeypatch):
    monkeypatch.setenv("PATTERN_REQUIRED_SIGNALS", '["blood_glucose","sleep_duration"]')
    assert Settings(_env_file=None).pattern_required_signals == ["blood_glucose", "sleep_duration"]


def test_shared_observed_change_calculations_and_provenance_are_identical(upstream):
    data, _, _ = upstream
    change(data, "blood_glucose")
    body = status()
    with TestClient(app) as client:
        observed = client.get("/patients/maya/observed-change", params=WINDOWS).json()
    for metric in BASELINES:
        comparison = next(item for item in observed["metrics"] if item["metric_type"] == metric)
        assert signal(body, metric)["comparison"] == comparison


def test_all_cursor_pages_participate_in_pattern_analysis(upstream):
    data, calls, _ = upstream
    change(data, "blood_glucose", "blood_pressure_systolic", "resting_heart_rate")
    data["pages"] = [page(data["samples"][:15], "page-two"), page(data["samples"][15:])]
    body = status()
    assert body["status"] == "change_to_review"
    assert calls[1].url.params["cursor"] == "page-two"
    assert len(calls) == 3


def test_output_is_deterministic_and_contains_no_diagnosis_or_risk_fields(upstream):
    data, _, _ = upstream
    change(data, "blood_glucose", "resting_heart_rate")
    body = status()
    assert status() == body

    def check(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert not any(term in key.lower() for term in ("diagnos", "risk", "probability", "disease", "forecast"))
                assert key not in ("score", "total_score")
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(body)


@pytest.mark.parametrize("params", [
    {}, {**WINDOWS, "reference_start": "invalid"},
    {**WINDOWS, "reference_start": "2026-10-08"},
    {**WINDOWS, "recent_end": "2026-10-11"},
    {**WINDOWS, "recent_start": "2026-10-07"},
])
def test_invalid_windows_return_422_without_upstream_calls(upstream, params):
    _, calls, _ = upstream
    assert request_status(params).status_code == 422
    assert calls == []


@pytest.mark.parametrize("failure,code", [
    (httpx.ConnectError("unavailable"), 503),
    (httpx.ReadTimeout("timed out"), 504),
    (httpx.Response(500, json={"detail": "private upstream detail"}), 502),
])
def test_upstream_failures_remain_errors_not_missing_or_normal(upstream, failure, code):
    data, _, _ = upstream
    data["failure"] = failure
    response = request_status()
    assert response.status_code == code
    assert "detail" in response.json()
    assert "private upstream detail" not in response.text
    assert "status" not in response.json()
