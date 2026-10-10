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
METRIC_UNITS = {
    "blood_glucose": "mg/dL", "blood_pressure_systolic": "mmHg",
    "blood_pressure_diastolic": "mmHg", "resting_heart_rate": "bpm",
    "heart_rate_variability_sdnn": "ms", "skin_temperature": "degC",
    "body_temperature": "degC", "weight": "kg",
}
SOURCE = {
    "provider": "apple", "source": "HealthKit", "device": "Watch7,1",
    "device_type": "watch",
}


def sample(value, day, metric="blood_glucose", **fields):
    return {
        "timestamp": f"2026-10-{day:02d}T12:00:00Z",
        "type": metric, "value": value, "unit": METRIC_UNITS[metric],
        "source": SOURCE, **fields,
    }


def samples(reference=(100, 110, 120), recent=(130, 140, 150), metric="blood_glucose"):
    return [sample(value, 5 + index, metric) for index, value in enumerate(reference)] + [
        sample(value, 12 + index, metric) for index, value in enumerate(recent)
    ]


def page(records, cursor=None):
    return {"data": records, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}, "metadata": {}}


@pytest.fixture
def upstream(monkeypatch):
    data = {"samples": [], "sleep": [], "pages": None, "failures": {}}
    calls = []
    settings = Settings(
        _env_file=None,
        open_wearables_base_url="http://mock-wearables.test",
        open_wearables_api_key="test-key",
        open_wearables_user_id="test-user",
        nestwatch_patient_id="maya",
        observed_change_min_samples=3,
        observed_change_max_staleness_days=2,
    )
    monkeypatch.setattr(app.state, "settings", settings)

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
        if resource == "timeseries":
            if data["pages"] is not None:
                return httpx.Response(200, json=data["pages"].pop(0))
            return httpx.Response(200, json=page(data["samples"]))
        return httpx.Response(200, json=page(data["sleep"]))

    async def client_dependency():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield OpenWearablesClient(settings, http)

    monkeypatch.setitem(app.dependency_overrides, get_open_wearables_client, client_dependency)
    return data, calls


def compare(params=None):
    with TestClient(app) as client:
        return client.get("/patients/maya/observed-change", params=WINDOWS if params is None else params)


def result(response, metric="blood_glucose"):
    assert response.status_code == 200
    return next(item for item in response.json()["metrics"] if item["metric_type"] == metric)


@pytest.mark.parametrize("metric", list(METRIC_UNITS))
def test_normal_comparison_of_all_requested_metrics(upstream, metric):
    data, calls = upstream
    data["samples"] = samples(metric=metric)
    response = compare()
    item = result(response, metric)
    assert item["metric_name"]
    assert item["metric_definition"]
    assert item["unit"] == METRIC_UNITS[metric]
    assert item["reference_sample_count"] == item["recent_sample_count"] == 3
    assert item["reference_mean"] == 110
    assert item["recent_mean"] == 140
    assert item["absolute_change"] == 30
    assert item["enough_data"] is True
    assert item["status"] == "compared"
    assert item["reasons"] == []
    if metric in ("skin_temperature", "body_temperature"):
        assert item["percent_change"] is None
        assert item["percent_change_unavailable_reason"] == "temperature_unit_not_ratio_scale"
    else:
        assert item["percent_change"] == pytest.approx(30 / 110 * 100)
        assert item["percent_change_unavailable_reason"] is None
    body = response.json()
    assert [item["metric_type"] for item in body["metrics"]] == list(METRIC_UNITS)
    assert body["patient_id"] == "maya"
    assert body["synthetic"] is True
    assert body["analysis_type"] == "observed_change"
    assert body["reference_window"] == {"start_date": "2026-10-01", "end_date": "2026-10-07"}
    assert body["recent_window"] == {"start_date": "2026-10-12", "end_date": "2026-10-14"}
    assert body["policy"] == {
        "aggregation": "sample_mean", "minimum_samples_per_window": 3,
        "max_staleness_days": 2, "freshness_relative_to": "each_window_end",
    }
    assert len(calls) == 2
    assert calls[0].url.params["start_time"] == "2026-10-01"
    assert calls[0].url.params["end_time"] == "2026-10-14"


@pytest.mark.parametrize("reference,recent,expected", [
    ((100, 100, 100), (100, 100, 100), 0),
    ((120, 130, 140), (90, 100, 110), -30),
])
def test_zero_and_negative_changes_are_descriptive(upstream, reference, recent, expected):
    data, _ = upstream
    data["samples"] = samples(reference, recent)
    item = result(compare())
    assert item["absolute_change"] == expected
    assert item["status"] == "compared"
    assert "normal" not in item.values()


def test_missing_metrics_always_have_explicit_insufficient_data(upstream):
    body = compare().json()
    assert len(body["metrics"]) == 8
    for item in body["metrics"]:
        assert item["status"] == "insufficient_data"
        assert item["enough_data"] is False
        assert item["reference_sample_count"] == item["recent_sample_count"] == 0
        assert item["reference_mean"] is None
        assert item["recent_mean"] is None
        assert item["absolute_change"] is None
        assert item["percent_change"] is None
        assert item["unit"] is None
        assert item["reference_provenance"] == item["recent_provenance"] == []
        assert item["reasons"] == ["missing_reference_data", "missing_recent_data"]


@pytest.mark.parametrize("missing", ["reference", "recent"])
def test_missing_one_window_does_not_create_zero_values(upstream, missing):
    data, _ = upstream
    data["samples"] = samples(reference=() if missing == "reference" else (100, 110, 120),
                              recent=() if missing == "recent" else (130, 140, 150))
    item = result(compare())
    assert item[f"{missing}_mean"] is None
    assert item[f"{missing}_sample_count"] == 0
    assert item["reasons"] == [f"missing_{missing}_data"]
    assert item["absolute_change"] is None
    assert item["enough_data"] is False


@pytest.mark.parametrize("metric", ["blood_glucose", "weight"])
@pytest.mark.parametrize("window", ["reference", "recent"])
def test_too_few_samples_in_either_window(upstream, metric, window):
    data, _ = upstream
    data["samples"] = samples(reference=(110,) if window == "reference" else (100, 110, 120),
                              recent=(140,) if window == "recent" else (130, 140, 150), metric=metric)
    item = result(compare(), metric)
    assert item[f"{window}_sample_count"] == 1
    assert item[f"{window}_mean"] is not None
    assert f"too_few_{window}_samples" in item["reasons"]
    assert item["enough_data"] is False
    assert item["absolute_change"] is None
    assert item["percent_change"] is None


@pytest.mark.parametrize("window", ["reference", "recent"])
def test_stale_data_is_insufficient_even_with_enough_samples(upstream, window):
    data, _ = upstream
    observations = samples()
    stale_days = (1, 2, 3) if window == "reference" else (8, 9, 10)
    offset = 0 if window == "reference" else 3
    for index, day in enumerate(stale_days):
        observations[offset + index]["timestamp"] = f"2026-10-{day:02d}T12:00:00Z"
    data["samples"] = observations
    # The recent window must be long enough to contain stale samples.
    params = {**WINDOWS, "recent_start": "2026-10-08"}
    item = result(compare(params))
    assert item[f"{window}_sample_count"] == 3
    assert item["reasons"] == [f"stale_{window}_data"]
    assert item["status"] == "insufficient_data"
    assert item["absolute_change"] is None
    assert item["percent_change"] is None


def test_freshness_boundary_is_relative_to_window_end(upstream):
    data, _ = upstream
    data["samples"] = [sample(100, 5) for _ in range(3)] + [sample(120, 12) for _ in range(3)]
    item = result(compare())
    assert item["status"] == "compared"
    assert item["reference_latest_timestamp"] == "2026-10-05T12:00:00Z"
    assert item["recent_latest_timestamp"] == "2026-10-12T12:00:00Z"


def test_zero_reference_mean_has_safe_null_percent(upstream):
    data, _ = upstream
    data["samples"] = samples(reference=(0, 0, 0), recent=(90, 100, 110))
    item = result(compare())
    assert item["reference_mean"] == 0
    assert item["absolute_change"] == 100
    assert item["percent_change"] is None
    assert item["percent_change_unavailable_reason"] == "zero_reference_mean"
    assert item["enough_data"] is True


def test_negative_baseline_does_not_produce_misleading_percent(upstream):
    data, _ = upstream
    data["samples"] = samples(reference=(-5, -5, -5), recent=(1, 1, 1))
    item = result(compare())
    assert item["absolute_change"] == 6
    assert item["percent_change"] is None
    assert item["percent_change_unavailable_reason"] == "negative_reference_mean"


def test_kelvin_temperature_allows_ratio_percent_change(upstream):
    data, _ = upstream
    data["samples"] = [{**item, "unit": "K"} for item in samples(reference=(300, 300, 300), recent=(303, 303, 303), metric="body_temperature")]
    item = result(compare(), "body_temperature")
    assert item["absolute_change"] == 3
    assert item["percent_change"] == pytest.approx(1)


def test_provider_source_and_device_provenance_is_preserved(upstream):
    data, _ = upstream
    observations = samples()
    other = {"provider": "withings", "source": "Withings", "device": "scale", "device_type": "scale"}
    observations[1]["source"] = other
    data["samples"] = observations
    item = result(compare())
    assert item["reference_provenance"] == [{**SOURCE, "sample_count": 2}, {**other, "sample_count": 1}]
    assert item["recent_provenance"] == [{**SOURCE, "sample_count": 3}]
    assert item["provenance_changed"] is True
    assert item["enough_data"] is True


def test_unknown_provenance_stays_unknown(upstream):
    data, _ = upstream
    data["samples"] = [{**item, "source": None} for item in samples()]
    item = result(compare())
    unknown = {"provider": None, "source": None, "device": None, "device_type": None, "sample_count": 3}
    assert item["reference_provenance"] == item["recent_provenance"] == [unknown]
    assert item["provenance_changed"] is False


@pytest.mark.parametrize("within_window", [False, True])
def test_incompatible_units_never_get_combined_or_converted(upstream, within_window):
    data, _ = upstream
    observations = samples()
    for index in ([0] if within_window else [3, 4, 5]):
        observations[index]["unit"] = "mmol/L"
    data["samples"] = observations
    item = result(compare())
    assert item["unit"] is None
    assert item["available_units"] == ["mg/dL", "mmol/L"]
    assert item["reasons"] == ["incompatible_units"]
    assert item["enough_data"] is False
    assert item["absolute_change"] is None
    assert item["percent_change"] is None
    if within_window:
        assert item["reference_mean"] is None
    else:
        assert item["reference_units"] == ["mg/dL"]
        assert item["recent_units"] == ["mmol/L"]


def test_empty_unit_is_explicitly_insufficient(upstream):
    data, _ = upstream
    data["samples"] = [{**item, "unit": ""} for item in samples()]
    item = result(compare())
    assert item["reasons"] == ["missing_unit"]
    assert item["reference_mean"] is None
    assert item["absolute_change"] is None


def test_only_in_window_measurements_are_analyzed_using_utc(upstream):
    data, _ = upstream
    timestamps = [
        (90, "2026-09-30T23:30:00-07:00"),
        (100, "2026-10-07T22:00:00Z"),
        (110, "2026-10-07T23:59:59.999999Z"),
        (999, "2026-10-08T00:00:00Z"),
        (120, "2026-10-11T23:30:00-07:00"),
        (130, "2026-10-14T22:00:00Z"),
        (140, "2026-10-14T23:59:59.999999Z"),
        (999, "2026-10-15T00:00:00Z"),
    ]
    data["samples"] = [sample(value, 1, timestamp=stamp) for value, stamp in timestamps]
    data["samples"].append({**sample(999, 5), "type": "heart_rate", "unit": "bpm"})
    data["sleep"] = [{
        "id": "sleep", "start_time": "2026-10-12T00:00:00Z",
        "end_time": "2026-10-12T08:00:00Z", "duration_seconds": 28800, "source": SOURCE,
    }]
    response = compare()
    item = result(response)
    assert item["reference_sample_count"] == item["recent_sample_count"] == 3
    assert item["reference_mean"] == 100
    assert item["recent_mean"] == 130
    assert item["absolute_change"] == 30
    assert {row["metric_type"] for row in response.json()["metrics"]} == set(METRIC_UNITS)


def test_pagination_contributes_all_samples(upstream):
    data, calls = upstream
    observations = samples()
    data["pages"] = [page(observations[:2], "next"), page(observations[2:])]
    item = result(compare())
    assert item["reference_sample_count"] == item["recent_sample_count"] == 3
    assert item["enough_data"] is True
    assert calls[1].url.params["cursor"] == "next"


def test_configurable_minimum_and_freshness_are_applied(upstream, monkeypatch):
    data, _ = upstream
    data["samples"] = [sample(100, 1), sample(120, 2), sample(130, 12), sample(150, 13)]
    assert result(compare())["enough_data"] is False
    monkeypatch.setattr(app.state, "settings", app.state.settings.model_copy(update={
        "observed_change_min_samples": 2, "observed_change_max_staleness_days": 5,
    }))
    response = compare()
    assert result(response)["enough_data"] is True
    assert response.json()["policy"]["minimum_samples_per_window"] == 2
    assert response.json()["policy"]["max_staleness_days"] == 5


def test_zero_day_freshness_requires_a_sample_on_end_date(upstream, monkeypatch):
    data, _ = upstream
    data["samples"] = [sample(100, 6) for _ in range(3)] + [sample(120, 13) for _ in range(3)]
    monkeypatch.setattr(app.state, "settings", app.state.settings.model_copy(update={"observed_change_max_staleness_days": 0}))
    item = result(compare())
    assert item["reasons"] == ["stale_reference_data", "stale_recent_data"]


@pytest.mark.parametrize("changes", [
    None, {"reference_start": "invalid"},
    {"reference_start": "2026-10-08"}, {"recent_end": "2026-10-11"},
    {"recent_start": "2026-10-07"},
    {"recent_start": "2026-10-01", "recent_end": "2026-10-03"},
])
def test_invalid_or_overlapping_windows_do_not_fetch(upstream, changes):
    _, calls = upstream
    params = {} if changes is None else {**WINDOWS, **changes}
    response = compare(params)
    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("resource", ["timeseries", "events/sleep"])
@pytest.mark.parametrize("failure,status", [
    (httpx.ConnectError("private upstream error"), 503),
    (httpx.ReadTimeout("private upstream error"), 504),
    (httpx.Response(401, json={"detail": "private upstream error"}), 502),
])
def test_upstream_failures_are_not_reported_as_missing_or_normal(upstream, resource, failure, status):
    data, _ = upstream
    data["samples"] = samples()
    data["failures"][resource] = failure
    response = compare()
    assert response.status_code == status
    assert "metrics" not in response.json()
    assert "private upstream error" not in response.text


def test_overflowing_mean_is_insufficient_not_invalid_json(upstream):
    data, _ = upstream
    data["samples"] = samples(reference=(1e308, 1e308, 1e308))
    item = result(compare())
    assert item["reference_mean"] is None
    assert item["reasons"] == ["non_finite_reference_mean"]
    assert item["absolute_change"] is None


def test_overflowing_percent_is_null_while_absolute_change_is_valid(upstream):
    data, _ = upstream
    data["samples"] = samples(reference=(1e-308, 1e-308, 1e-308))
    item = result(compare())
    assert item["enough_data"] is True
    assert item["absolute_change"] == pytest.approx(140)
    assert item["percent_change"] is None
    assert item["percent_change_unavailable_reason"] == "non_finite_percent_change"


def test_policy_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("OBSERVED_CHANGE_MIN_SAMPLES", "5")
    monkeypatch.setenv("OBSERVED_CHANGE_MAX_STALENESS_DAYS", "0")
    settings = Settings(_env_file=None)
    assert settings.observed_change_min_samples == 5
    assert settings.observed_change_max_staleness_days == 0


@pytest.mark.parametrize("field,value", [
    ("observed_change_min_samples", 1), ("observed_change_max_staleness_days", -1),
])
def test_invalid_policy_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
