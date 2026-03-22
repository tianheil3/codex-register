from contextlib import contextmanager
from types import SimpleNamespace

import src.config.settings as settings_module
import src.core.register as register_module
from src.config.constants import EmailServiceType
from src.core.openai.oauth import OAuthStart
from src.services.base import BaseEmailService


class DummyEmailService(BaseEmailService):
    def __init__(self):
        super().__init__(EmailServiceType.TEMPMAIL, "dummy")

    def create_email(self, config=None):
        return {"email": "tester@example.com", "service_id": "svc-1"}

    def get_verification_code(
        self,
        email,
        email_id=None,
        timeout=60,
        pattern=r"(?<!\d)(\d{6})(?!\d)",
        otp_sent_at=None,
    ):
        return "123456"

    def list_emails(self, **kwargs):
        return []

    def delete_email(self, email_id):
        return True

    def check_health(self):
        return True


def _browser_settings():
    return SimpleNamespace(
        openai_client_id="client-id",
        openai_auth_url="https://auth.openai.com/oauth/authorize",
        openai_token_url="https://auth.openai.com/oauth/token",
        openai_redirect_uri="http://localhost:1455/auth/callback",
        openai_scope="openid email profile offline_access",
        registration_mode="browser",
        registration_browser_headless=True,
        registration_browser_timeout=120,
    )


def _make_engine(monkeypatch, settings=None):
    monkeypatch.setattr(
        register_module,
        "get_settings",
        lambda: settings or _browser_settings(),
    )
    return register_module.RegistrationEngine(email_service=DummyEmailService())


def test_settings_default_to_browser_registration_mode():
    settings = settings_module.Settings()

    assert settings.registration_mode == "browser"
    assert settings.registration_browser_headless is True


def test_browser_registration_runner_is_available():
    from src.core.register_browser import (
        BrowserRegistrationArtifacts,
        BrowserRegistrationRunner,
    )

    assert BrowserRegistrationRunner is not None
    assert BrowserRegistrationArtifacts is not None


def test_registration_engine_browser_mode_uses_runner_and_access_token_workspace_lookup(
    monkeypatch,
):
    engine = _make_engine(monkeypatch)

    monkeypatch.setattr(engine, "_check_ip_location", lambda: (True, "US"))
    monkeypatch.setattr(engine, "_init_session", lambda: True)

    def fake_start_oauth():
        engine.oauth_start = OAuthStart(
            auth_url="https://auth.openai.com/oauth/authorize?state=state-1",
            state="state-1",
            code_verifier="verifier-1",
            redirect_uri="http://localhost:1455/auth/callback",
        )
        return True

    monkeypatch.setattr(engine, "_start_oauth", fake_start_oauth)
    monkeypatch.setattr(
        engine,
        "_run_browser_registration_flow",
        lambda: SimpleNamespace(
            callback_url="http://localhost:1455/auth/callback?code=code-1&state=state-1",
            session_token="session-token",
            cookies="oai-did=device-1; __Secure-next-auth.session-token=session-token",
            is_existing_account=False,
            password_used="Password123!",
        ),
    )
    monkeypatch.setattr(
        engine,
        "_handle_oauth_callback",
        lambda callback_url: {
            "account_id": "account-1",
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "id_token": "id-1",
        },
    )
    monkeypatch.setattr(
        engine,
        "_get_workspace_id_from_access_token",
        lambda access_token: "ws-browser",
    )

    monkeypatch.setattr(
        engine,
        "_get_device_id",
        lambda: (_ for _ in ()).throw(
            AssertionError("legacy HTTP flow should not run in browser mode")
        ),
    )
    monkeypatch.setattr(
        engine,
        "_submit_signup_form",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy signup flow should not run")
        ),
    )
    monkeypatch.setattr(
        engine,
        "_get_workspace_id",
        lambda: (_ for _ in ()).throw(
            AssertionError("cookie workspace parsing should not run in browser mode")
        ),
    )
    monkeypatch.setattr(
        engine,
        "_select_workspace",
        lambda workspace_id: (_ for _ in ()).throw(
            AssertionError("workspace/select should not run in browser mode")
        ),
    )

    result = engine.run()

    assert result.success is True
    assert result.account_id == "account-1"
    assert result.access_token == "access-1"
    assert result.refresh_token == "refresh-1"
    assert result.id_token == "id-1"
    assert result.workspace_id == "ws-browser"
    assert result.session_token == "session-token"
    assert result.password == "Password123!"
    assert result.cookies.startswith("oai-did=device-1")


def test_save_to_database_persists_browser_cookies(monkeypatch):
    engine = _make_engine(monkeypatch)
    captured = {}

    @contextmanager
    def fake_get_db():
        yield object()

    monkeypatch.setattr(register_module, "get_db", fake_get_db)
    monkeypatch.setattr(
        register_module.crud,
        "create_account",
        lambda db, **kwargs: captured.update(kwargs) or SimpleNamespace(id=1),
    )

    result = register_module.RegistrationResult(
        success=True,
        email="tester@example.com",
        password="Password123!",
        account_id="account-1",
        workspace_id="ws-browser",
        access_token="access-1",
        refresh_token="refresh-1",
        id_token="id-1",
        session_token="session-token",
        logs=[],
        metadata={},
        source="register",
        cookies="oai-did=device-1; __Secure-next-auth.session-token=session-token",
    )

    assert engine.save_to_database(result) is True
    assert captured["cookies"].startswith("oai-did=device-1")


def test_execution_mode_http_override_skips_browser_mode(monkeypatch):
    engine = _make_engine(monkeypatch)
    engine.execution_mode = "curl_cffi"

    assert engine._is_browser_mode() is False


def test_execution_mode_playwright_override_forces_browser_mode(monkeypatch):
    settings = SimpleNamespace(**vars(_browser_settings()))
    settings.registration_mode = "http"
    engine = _make_engine(monkeypatch, settings=settings)
    engine.execution_mode = "playwright"

    assert engine._is_browser_mode() is True
