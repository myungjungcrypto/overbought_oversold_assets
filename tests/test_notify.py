"""텔레그램 스텁 테스트 (F1) — 네트워크 호출 없음."""

import pytest

from oo_scan import telegram_stub


def test_noop_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """토큰 미설정이면 전송 시도 없이 False."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def boom(*a: object, **k: object) -> None:  # pragma: no cover - 호출되면 안 됨
        raise AssertionError("네트워크 호출이 발생하면 안 된다")

    monkeypatch.setattr(telegram_stub.urllib.request, "urlopen", boom)
    assert telegram_stub.is_configured() is False
    assert telegram_stub.send_message("hi") is False


def test_send_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """설정 시 urlopen이 호출되고 2xx면 True."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    calls: list[str] = []

    class FakeResp:
        status = 200

        def __enter__(self) -> "FakeResp":
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def fake_urlopen(req: object, timeout: float = 0) -> FakeResp:
        calls.append(getattr(req, "full_url", ""))
        return FakeResp()

    monkeypatch.setattr(telegram_stub.urllib.request, "urlopen", fake_urlopen)
    assert telegram_stub.send_message("리포트") is True
    assert calls and "api.telegram.org" in calls[0]


def test_send_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """네트워크 오류는 False로 삼킨다 (파이프라인을 죽이지 않음)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")

    def fail(*a: object, **k: object) -> None:
        raise OSError("down")

    monkeypatch.setattr(telegram_stub.urllib.request, "urlopen", fail)
    assert telegram_stub.send_message("리포트") is False
