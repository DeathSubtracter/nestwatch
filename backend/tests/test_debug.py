import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.open_wearables import OpenWearablesClient
from app.config import Settings
from app.main import app
from app.routes.debug import get_open_wearables_client


@pytest.fixture
def mock_upstream(monkeypatch):
    settings = Settings(
        _env_file=None,
        open_wearables_base_url="http://mock-wearables.test",
        open_wearables_api_key="mock-key",
        open_wearables_user_id="mock-user",
        nestwatch_patient_id="mock-patient",
    )

    def install(handler):
        async def client_dependency():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                yield OpenWearablesClient(settings, http)

        monkeypatch.setitem(app.dependency_overrides, get_open_wearables_client, client_dependency)

    return install


@pytest.mark.parametrize("resource", ["timeseries", "sleep"])
def test_debug_uses_real_client_with_mock_transport(mock_upstream, resource):
    record = {"source": {"provider": "apple", "device_type": "watch"}, "value": 72}

    def handler(request):
        path = "timeseries" if resource == "timeseries" else "events/sleep"
        assert request.url.path == f"/api/v1/users/mock-user/{path}"
        assert request.headers["X-Open-Wearables-API-Key"] == "mock-key"
        if resource == "timeseries":
            assert request.url.params.get_list("types") == ["heart_rate", "blood_glucose"]
        return httpx.Response(200, json={
            "data": [record], "pagination": {"has_more": False, "next_cursor": None}, "metadata": {}
        })

    mock_upstream(handler)
    with TestClient(app) as client:
        params = [("start_date", "2026-10-01"), ("end_date", "2026-10-07")]
        if resource == "timeseries":
            params += [("types", "heart_rate"), ("types", "blood_glucose")]
        response = client.get(f"/debug/open-wearables/{resource}", params=params)
    assert response.status_code == 200
    assert response.json() == {"data": [record], "count": 1}


@pytest.mark.parametrize("resource", ["timeseries", "sleep"])
@pytest.mark.parametrize("failure,status", [("connection", 503), ("timeout", 504), ("http", 502)])
def test_debug_upstream_errors(mock_upstream, resource, failure, status):
    def handler(request):
        if failure == "connection":
            raise httpx.ConnectError("secret information", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("secret information", request=request)
        return httpx.Response(401, json={"detail": "secret information"})

    mock_upstream(handler)
    with TestClient(app) as client:
        response = client.get(f"/debug/open-wearables/{resource}", params={
            "start_date": "2026-10-01", "end_date": "2026-10-07"
        })
    assert response.status_code == status
    assert "detail" in response.json()
    assert "secret information" not in response.text


@pytest.mark.parametrize("resource", ["timeseries", "sleep"])
@pytest.mark.parametrize("params", [
    {},
    {"start_date": "invalid", "end_date": "2026-10-07"},
    {"start_date": "2026-10-07", "end_date": "2026-10-01"},
])
def test_debug_validates_dates_without_upstream_request(mock_upstream, resource, params):
    def handler(request):
        pytest.fail("Invalid dates must not contact upstream")

    mock_upstream(handler)
    with TestClient(app) as client:
        response = client.get(f"/debug/open-wearables/{resource}", params=params)
    assert response.status_code == 422
