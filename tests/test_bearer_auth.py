import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import TOKEN_ENV_VAR, UNSET_WARNING, install_bearer_auth

TOKEN = "s3cret-token-with-enough-entropy-to-be-realistic"


def _app_with_auth(monkeypatch, token: str | None):
    if token is None:
        monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(TOKEN_ENV_VAR, token)

    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/diagnose")
    def diagnose():
        return {"root_cause": "missing configuration"}

    @app.get("/incidents")
    def incidents():
        return []

    install_bearer_auth(app)
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    return _app_with_auth(monkeypatch, TOKEN)


def test_correct_token_is_accepted(client):
    response = client.post("/diagnose", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.json()["root_cause"] == "missing configuration"


def test_missing_header_is_rejected(client):
    response = client.post("/diagnose")

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_wrong_token_is_rejected(client):
    response = client.post("/diagnose", headers={"Authorization": "Bearer not-the-token"})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_a_correct_prefix_is_still_rejected(client):
    response = client.post("/diagnose", headers={"Authorization": f"Bearer {TOKEN[:20]}"})

    assert response.status_code == 401


def test_token_with_trailing_whitespace_is_rejected(client):
    response = client.post("/diagnose", headers={"Authorization": f"Bearer {TOKEN} "})

    assert response.status_code == 401


def test_wrong_scheme_is_rejected(client):
    response = client.post("/diagnose", headers={"Authorization": f"Basic {TOKEN}"})

    assert response.status_code == 401


def test_bare_token_without_the_scheme_is_rejected(client):
    response = client.post("/diagnose", headers={"Authorization": TOKEN})

    assert response.status_code == 401


def test_scheme_is_case_insensitive(client):
    response = client.post("/diagnose", headers={"Authorization": f"bearer {TOKEN}"})

    assert response.status_code == 200


def test_health_is_exempt(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_docs_are_exempt(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_every_other_route_is_protected(client):
    assert client.get("/incidents").status_code == 401
    assert client.get("/incidents", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_unset_token_disables_auth_with_a_loud_warning(monkeypatch, capsys):
    client = _app_with_auth(monkeypatch, None)

    warning = capsys.readouterr().err
    assert UNSET_WARNING in warning
    assert "auth disabled" in warning
    assert client.post("/diagnose").status_code == 200


def test_empty_token_is_treated_as_unset(monkeypatch, capsys):
    client = _app_with_auth(monkeypatch, "")

    assert UNSET_WARNING in capsys.readouterr().err
    assert client.post("/diagnose").status_code == 200


def test_install_returns_the_loaded_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, TOKEN)
    assert install_bearer_auth(FastAPI()) == TOKEN

    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    assert install_bearer_auth(FastAPI()) is None