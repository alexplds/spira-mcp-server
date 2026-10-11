import json

import httpx
import pytest
import respx

from spira_mcp import server
from tests.conftest import BASE, SVC


def body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


# --- URL building / auth / query params ------------------------------------


def test_service_url_uses_default_api_version():
    assert server._service_url("projects/1") == f"{SVC}/projects/1"


def test_service_url_uses_configured_api_version(monkeypatch):
    monkeypatch.setenv("SPIRA_API_VERSION", "v7_0")
    assert server._service_url("projects/1") == f"{BASE}/Services/v7_0/RestService.svc/projects/1"


@respx.mock
async def test_request_sends_auth_params_and_headers():
    route = respx.get(f"{SVC}/projects/1").mock(return_value=httpx.Response(200, json={"ok": 1}))
    assert await server._request("GET", "projects/1") == {"ok": 1}
    request = route.calls.last.request
    assert request.url.params["username"] == "test.user"
    assert request.url.params["api-key"] == "test-key"
    assert request.headers["accept"] == "application/json"


@respx.mock
async def test_query_params_are_merged_with_auth_params():
    route = respx.get(f"{SVC}/projects/1/test-cases").mock(
        return_value=httpx.Response(200, json=[])
    )
    await server.spira_list_test_cases(project_id=1, starting_row=11, number_of_rows=5)
    params = route.calls.last.request.url.params
    assert params["starting_row"] == "11"
    assert params["number_of_rows"] == "5"
    assert params["username"] == "test.user"
    assert params["api-key"] == "test-key"


@respx.mock
async def test_empty_response_body_returns_none():
    respx.delete(f"{SVC}/projects/1/test-cases/9").mock(return_value=httpx.Response(200))
    assert await server._request("DELETE", "projects/1/test-cases/9") is None


# --- project id resolution --------------------------------------------------


def test_resolve_project_id_explicit_wins(monkeypatch):
    monkeypatch.setenv("SPIRA_DEFAULT_PROJECT_ID", "7")
    assert server._resolve_project_id(3) == 3


def test_resolve_project_id_uses_default_env(monkeypatch):
    monkeypatch.setenv("SPIRA_DEFAULT_PROJECT_ID", "7")
    assert server._resolve_project_id(None) == 7


def test_resolve_project_id_missing_raises():
    with pytest.raises(RuntimeError, match="SPIRA_DEFAULT_PROJECT_ID"):
        server._resolve_project_id(None)


@respx.mock
async def test_tool_uses_default_project_from_env(monkeypatch):
    monkeypatch.setenv("SPIRA_DEFAULT_PROJECT_ID", "4")
    route = respx.get(f"{SVC}/projects/4/test-cases/12").mock(
        return_value=httpx.Response(200, json={"TestCaseId": 12})
    )
    assert await server.spira_get_test_case(12) == {"TestCaseId": 12}
    assert route.called


async def test_tool_without_project_raises():
    with pytest.raises(RuntimeError, match="No project_id"):
        await server.spira_get_test_case(1)


# --- CRUD -------------------------------------------------------------------


@respx.mock
async def test_create_test_case_body():
    route = respx.post(f"{SVC}/projects/2/test-cases").mock(
        return_value=httpx.Response(200, json={"TestCaseId": 100})
    )
    result = await server.spira_create_test_case(
        name="Login works",
        description="desc",
        test_case_priority_id=3,
        test_case_folder_id=12,
        project_id=2,
    )
    assert result == {"TestCaseId": 100}
    assert body_of(route) == {
        "Name": "Login works",
        "Description": "desc",
        "TestCaseStatusId": 0,
        "TestCaseTypeId": 0,
        "TestCasePriorityId": 3,
        "TestCaseFolderId": 12,
    }


@respx.mock
async def test_update_fetches_merges_and_puts_with_concurrency_date():
    current = {
        "TestCaseId": 5,
        "Name": "Old",
        "Description": "keep me",
        "TestCaseStatusId": 1,
        "ConcurrencyDate": "/Date(1700000000000)/",
    }
    get_route = respx.get(f"{SVC}/projects/2/test-cases/5").mock(
        return_value=httpx.Response(200, json=current)
    )
    put_route = respx.put(f"{SVC}/projects/2/test-cases").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    await server.spira_update_test_case(5, name="New", test_case_status_id=4, project_id=2)
    assert get_route.called
    sent = body_of(put_route)
    assert sent["Name"] == "New"
    assert sent["TestCaseStatusId"] == 4
    assert sent["Description"] == "keep me"  # untouched field preserved
    assert sent["ConcurrencyDate"] == "/Date(1700000000000)/"


@respx.mock
async def test_update_missing_test_case_raises():
    respx.get(f"{SVC}/projects/2/test-cases/5").mock(return_value=httpx.Response(200))
    with pytest.raises(RuntimeError, match="not found"):
        await server.spira_update_test_case(5, name="x", project_id=2)


@respx.mock
async def test_delete_test_case():
    route = respx.delete(f"{SVC}/projects/2/test-cases/5").mock(return_value=httpx.Response(200))
    message = await server.spira_delete_test_case(5, project_id=2)
    assert route.called
    assert message == "Test case 5 deleted from project 2."


# --- lookup values ----------------------------------------------------------


@respx.mock
async def test_lookup_values_resolves_template_then_three_endpoints():
    project = respx.get(f"{SVC}/projects/2").mock(
        return_value=httpx.Response(200, json={"ProjectTemplateId": 9})
    )
    types = respx.get(f"{SVC}/project-templates/9/test-cases/types").mock(
        return_value=httpx.Response(200, json=[{"TestCaseTypeId": 1, "Name": "Functional"}])
    )
    statuses = respx.get(f"{SVC}/project-templates/9/test-cases/statuses").mock(
        return_value=httpx.Response(200, json=[{"TestCaseStatusId": 2, "Name": "Draft"}])
    )
    priorities = respx.get(f"{SVC}/project-templates/9/test-cases/priorities").mock(
        return_value=httpx.Response(200, json=[{"PriorityId": 3, "Name": "High"}])
    )
    result = await server.spira_list_lookup_values(project_id=2)
    assert project.called and types.called and statuses.called and priorities.called
    assert result == {
        "types": [{"id": 1, "name": "Functional"}],
        "statuses": [{"id": 2, "name": "Draft"}],
        "priorities": [{"id": 3, "name": "High"}],
    }


# --- test steps -------------------------------------------------------------


@respx.mock
async def test_list_test_steps():
    route = respx.get(f"{SVC}/projects/2/test-cases/5/test-steps").mock(
        return_value=httpx.Response(200, json=[{"TestStepId": 1}])
    )
    assert await server.spira_list_test_steps(5, project_id=2) == [{"TestStepId": 1}]
    assert route.called


@respx.mock
async def test_add_test_step_omits_null_fields():
    route = respx.post(f"{SVC}/projects/2/test-cases/5/test-steps").mock(
        return_value=httpx.Response(200, json={"TestStepId": 1})
    )
    await server.spira_add_test_step(5, "Click login", project_id=2)
    assert body_of(route) == {"Description": "Click login"}


@respx.mock
async def test_add_test_step_includes_provided_fields():
    route = respx.post(f"{SVC}/projects/2/test-cases/5/test-steps").mock(
        return_value=httpx.Response(200, json={"TestStepId": 1})
    )
    await server.spira_add_test_step(
        5,
        "Click login",
        expected_result="Dashboard opens",
        sample_data="user1",
        position=2,
        project_id=2,
    )
    assert body_of(route) == {
        "Description": "Click login",
        "ExpectedResult": "Dashboard opens",
        "SampleData": "user1",
        "Position": 2,
    }


# --- errors and config ------------------------------------------------------


@respx.mock
async def test_http_error_raises_runtime_error_with_status_and_truncated_body():
    respx.get(f"{SVC}/projects/2/test-cases/5").mock(
        return_value=httpx.Response(404, text="x" * 2000)
    )
    with pytest.raises(RuntimeError) as exc:
        await server.spira_get_test_case(5, project_id=2)
    message = str(exc.value)
    assert "404" in message
    assert "GET projects/2/test-cases/5" in message
    assert "x" * 500 in message
    assert "x" * 501 not in message


@pytest.mark.parametrize("name", ["SPIRA_BASE_URL", "SPIRA_USERNAME", "SPIRA_API_KEY"])
async def test_missing_config_raises(monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(RuntimeError, match="not configured"):
        await server.spira_get_test_case(1, project_id=1)


def test_missing_env_lists_unset_vars(monkeypatch):
    monkeypatch.delenv("SPIRA_API_KEY")
    assert server._missing_env() == ["SPIRA_API_KEY"]


def test_timeout_default_and_override(monkeypatch):
    assert server._timeout() == 30.0
    monkeypatch.setenv("SPIRA_TIMEOUT", "5")
    assert server._timeout() == 5.0
    monkeypatch.setenv("SPIRA_TIMEOUT", "nonsense")
    assert server._timeout() == 30.0


async def test_all_tools_registered():
    tools = {t.name for t in await server.mcp.list_tools()}
    assert tools == {
        "spira_list_test_cases",
        "spira_get_test_case",
        "spira_create_test_case",
        "spira_update_test_case",
        "spira_delete_test_case",
        "spira_list_lookup_values",
        "spira_list_test_steps",
        "spira_add_test_step",
    }
