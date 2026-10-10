from datetime import date

import httpx
import pytest

from app.clients.open_wearables import OpenWearablesClient, OpenWearablesError
from app.config import Settings

pytestmark = pytest.mark.anyio
START = date(2026, 10, 1)
END = date(2026, 10, 7)
SOURCE = {
    "provider": "apple",
    "source": "HealthKit",
    "device": "Watch7,1",
    "device_type": "watch",
    "device_name": "Apple Watch",
}
SAMPLE = {
    "timestamp": "2026-10-01T12:30:00Z",
    "zone_offset": "-07:00",
    "type": "blood_glucose",
    "value": 105.5,
    "unit": "mg/dL",
    "source": SOURCE,
}
SESSION = {
    "id": "sleep-1",
    "start_time": "2026-10-01T22:30:00-07:00",
    "end_time": "2026-10-02T06:30:00-07:00",
    "duration_seconds": 28800,
    "source": SOURCE,
    "stages": {"deep_minutes": 90},
    "is_nap": False,
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        open_wearables_base_url="http://wearables.test:8000",
        open_wearables_api_key="mock-api-key",
        open_wearables_user_id="mock-user",
        nestwatch_patient_id="mock-patient",
    )


def page(data, has_more=False, cursor=None):
    return {
        "data": data,
        "pagination": {"has_more": has_more, "next_cursor": cursor},
        "metadata": {},
    }


@pytest.mark.parametrize(
    "method,resource,start_key,end_key,record",
    [
        ("get_timeseries", "timeseries", "start_time", "end_time", SAMPLE),
        ("get_sleep", "events/sleep", "start_date", "end_date", SESSION),
    ],
)
async def test_all_pages_and_preserved_records(
    settings, method, resource, start_key, end_key, record
):
    requests = []
    cursor = "opaque+cursor/with=padding"
    second = {**record, "source": None, "extra_field": "preserved"}

    def handler(request):
        requests.append(request)
        assert request.url.host == "wearables.test"
        assert request.url.path == f"/api/v1/users/mock-user/{resource}"
        assert request.headers["X-Open-Wearables-API-Key"] == "mock-api-key"
        assert request.url.params[start_key] == "2026-10-01"
        assert request.url.params[end_key] == "2026-10-07"
        assert request.url.params["limit"] == "1000"
        if method == "get_timeseries":
            assert request.url.params.get_list("types") == ["blood_glucose", "heart_rate"]
            assert request.url.params["resolution"] == "raw"
        else:
            assert "types" not in request.url.params
        if len(requests) == 1:
            assert "cursor" not in request.url.params
            return httpx.Response(200, json=page([record], True, cursor))
        assert request.url.params["cursor"] == cursor
        return httpx.Response(200, json=page([second]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenWearablesClient(settings, http)
        kwargs = {"types": ["blood_glucose", "heart_rate"]} if method == "get_timeseries" else {}
        result = await getattr(client, method)(START, END, **kwargs)
    assert result == [record, second]
    assert len(requests) == 2


async def test_empty_page_with_more_data(settings):
    requests = []

    def handler(request):
        requests.append(request)
        assert "types" not in request.url.params
        body = page([], True, "next") if len(requests) == 1 else page([SAMPLE])
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await OpenWearablesClient(settings, http).get_timeseries(START, END)
    assert result == [SAMPLE]
    assert len(requests) == 2


async def test_empty_result_stops_when_has_more_is_false(settings):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=page([], False, "unused-previous-cursor"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await OpenWearablesClient(settings, http).get_sleep(START, END) == []
    assert len(requests) == 1


@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500, 503])
async def test_upstream_http_errors_are_safe(settings, status):
    def handler(request):
        return httpx.Response(status, json={"detail": "private upstream content"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(OpenWearablesError) as error:
            await OpenWearablesClient(settings, http).get_timeseries(START, END)
    assert error.value.status_code == 502
    assert str(error.value) == f"Open Wearables returned HTTP {status}"


@pytest.mark.parametrize(
    "error_type,status", [(httpx.ConnectError, 503), (httpx.ReadError, 503), (httpx.ReadTimeout, 504)]
)
async def test_network_errors(settings, error_type, status):
    def handler(request):
        raise error_type("private connection information", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(OpenWearablesError) as error:
            await OpenWearablesClient(settings, http).get_sleep(START, END)
    assert error.value.status_code == status
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [[], {}, {"data": {}, "pagination": {"has_more": False}},
     {"data": ["invalid"], "pagination": {"has_more": False}},
     {"data": [], "pagination": {"has_more": "false"}},
     {"data": [], "pagination": None}],
)
async def test_invalid_response_envelope(settings, body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises(OpenWearablesError, match="invalid page"):
            await OpenWearablesClient(settings, http).get_timeseries(START, END)


async def test_invalid_json(settings):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content="not JSON"))
    ) as http:
        with pytest.raises(OpenWearablesError, match="invalid JSON"):
            await OpenWearablesClient(settings, http).get_sleep(START, END)


@pytest.mark.parametrize("cursor", [None, "", 123, "repeated"])
async def test_missing_or_repeated_cursor(settings, cursor):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=page([SAMPLE], True, cursor))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(OpenWearablesError, match="invalid pagination"):
            await OpenWearablesClient(settings, http).get_timeseries(START, END)
    assert len(requests) == (2 if cursor == "repeated" else 1)


@pytest.mark.parametrize("field", ["open_wearables_api_key", "open_wearables_user_id"])
async def test_missing_configuration_does_not_make_request(settings, field):
    settings = Settings(**{**settings.model_dump(), field: ""}, _env_file=None)

    def handler(request):
        pytest.fail("Missing configuration must not make an HTTP request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(OpenWearablesError) as error:
            await OpenWearablesClient(settings, http).get_sleep(START, END)
    assert error.value.status_code == 503


@pytest.mark.parametrize("method", ["get_timeseries", "get_sleep"])
async def test_reversed_dates_do_not_make_request(settings, method):
    def handler(request):
        pytest.fail("Invalid dates must not make an HTTP request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ValueError, match="start_date"):
            await getattr(OpenWearablesClient(settings, http), method)(END, START)
