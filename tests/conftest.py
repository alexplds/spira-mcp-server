import pytest

BASE = "https://spira.example.test"
SVC = f"{BASE}/Services/v6_0/RestService.svc"


@pytest.fixture(autouse=True)
def spira_env(monkeypatch):
    monkeypatch.setenv("SPIRA_BASE_URL", BASE + "/")  # trailing slash must be stripped
    monkeypatch.setenv("SPIRA_USERNAME", "test.user")
    monkeypatch.setenv("SPIRA_API_KEY", "test-key")
    monkeypatch.delenv("SPIRA_API_VERSION", raising=False)
    monkeypatch.delenv("SPIRA_DEFAULT_PROJECT_ID", raising=False)
    monkeypatch.delenv("SPIRA_TIMEOUT", raising=False)
