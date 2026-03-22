from src.config.constants import EmailServiceType
from src.core.register import RegistrationEngine, SignupFormResult
from src.services.base import BaseEmailService


class DummyEmailService(BaseEmailService):
    def __init__(self):
        super().__init__(EmailServiceType.TEMPMAIL, "dummy")

    def create_email(self, config=None):
        raise NotImplementedError

    def get_verification_code(
        self,
        email,
        email_id=None,
        timeout=60,
        pattern=r"(?<!\d)(\d{6})(?!\d)",
        otp_sent_at=None,
    ):
        raise NotImplementedError

    def list_emails(self, **kwargs):
        return []

    def delete_email(self, email_id):
        raise NotImplementedError

    def check_health(self):
        return True


class DummyCookies:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class DummySession:
    def __init__(self, values):
        self.cookies = DummyCookies(values)


class TrackingRegistrationEngine(RegistrationEngine):
    def __init__(self):
        super().__init__(email_service=DummyEmailService())
        self.events = []
        self.sent_otp_count = 0
        self.codes_to_return = ["111111", "222222"]
        self.validated_codes = []
        self.auth_url_checks = 0

    def _pop_test_otp_code(self, stage):
        if not self.codes_to_return:
            raise AssertionError(f"test setup exhausted OTP codes during {stage}")
        code = self.codes_to_return.pop(0)
        self.events.append(f"get_otp:{code}")
        return code

    def _check_ip_location(self):
        self.events.append("check_ip_location")
        return True, "US"

    def _create_email(self):
        self.events.append("create_email")
        self.email = "new-account@example.com"
        self.email_info = {"email": self.email, "service_id": "email-id"}
        return True

    def _init_session(self):
        self.events.append("init_session")
        self.session = DummySession(
            {"__Secure-next-auth.session-token": "session-token"}
        )
        return True

    def _start_oauth(self):
        self.events.append("start_oauth")
        return True

    def _is_browser_mode(self):
        return False

    def _get_device_id(self):
        self.events.append("get_device_id")
        return "device-id"

    def _check_sentinel(self, did):
        self.events.append(f"check_sentinel:{did}")
        return None

    def _submit_signup_form(self, did, sen_token):
        self.events.append(f"submit_signup_form:{did}")
        return SignupFormResult(success=True, page_type="password")

    def _register_password(self):
        self.events.append("register_password")
        self.password = "generated-password"
        return True, self.password

    def _send_verification_code(self, referer="https://auth.openai.com/create-account/password"):
        self.sent_otp_count += 1
        self.events.append(f"send_otp:{self.sent_otp_count}:{referer}")
        self._otp_sent_at = float(self.sent_otp_count)
        return True

    def _get_verification_code(self):
        return self._pop_test_otp_code("signup OTP retrieval")

    def _validate_verification_code(self, code):
        self.validated_codes.append(code)
        self.events.append(f"validate_otp:{code}")
        return True

    def _create_user_account(self):
        self.events.append("create_user_account")
        return True

    def _advance_login_authorization(self):
        code = self._pop_test_otp_code("login OTP retrieval")
        self.validated_codes.append(code)
        self.events.append(f"validate_otp:{code}")
        self.events.append("advance_login_authorization")
        return "workspace-id", "http://localhost:1455/auth/callback?code=code&state=state"

    def _try_reenter_login_flow(self):
        self.events.append("try_reenter_login_flow")
        return True

    def _submit_login_password_step(self):
        self.events.append("submit_login_password_step")
        return True

    def _get_workspace_id(self):
        self.events.append("get_workspace_id")
        return "workspace-id"

    def _select_workspace(self, workspace_id):
        self.events.append(f"select_workspace:{workspace_id}")
        return "https://example.com/continue"

    def _follow_redirects(self, start_url):
        self.events.append("follow_redirects")
        return "http://localhost:1455/auth/callback?code=code&state=state"

    def _handle_oauth_callback(self, callback_url):
        self.events.append("handle_oauth_callback")
        return {
            "account_id": "account-id",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "id_token": "id-token",
        }


def test_new_account_restarts_login_otp_flow_after_create_account():
    engine = TrackingRegistrationEngine()

    result = engine.run()

    assert result.success is True
    assert result.source == "register"
    assert result.password == "generated-password"
    assert result.session_token == "session-token"
    assert engine.sent_otp_count == 1
    assert engine.validated_codes == ["111111", "222222"]
    assert engine.events == [
        "check_ip_location",
        "create_email",
        "init_session",
        "start_oauth",
        "get_device_id",
        "check_sentinel:device-id",
        "submit_signup_form:device-id",
        "register_password",
        "send_otp:1:https://auth.openai.com/create-account/password",
        "get_otp:111111",
        "validate_otp:111111",
        "create_user_account",
        "get_otp:222222",
        "validate_otp:222222",
        "advance_login_authorization",
        "handle_oauth_callback",
    ]


def test_tracking_registration_engine_fails_clearly_when_signup_otp_pool_is_exhausted():
    engine = TrackingRegistrationEngine()
    engine.codes_to_return = []

    try:
        engine._get_verification_code()
    except AssertionError as exc:
        assert str(exc) == "test setup exhausted OTP codes during signup OTP retrieval"
    else:
        raise AssertionError("expected a clear assertion when signup OTP codes run out")


def test_tracking_registration_engine_fails_clearly_when_login_otp_pool_is_exhausted():
    engine = TrackingRegistrationEngine()
    engine.codes_to_return = []

    try:
        engine._advance_login_authorization()
    except AssertionError as exc:
        assert str(exc) == "test setup exhausted OTP codes during login OTP retrieval"
    else:
        raise AssertionError("expected a clear assertion when login OTP codes run out")
