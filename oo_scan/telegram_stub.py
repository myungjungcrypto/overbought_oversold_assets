"""텔레그램 알림 스텁 — 토큰이 없으면 조용히 no-op.

환경변수 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 가 모두 있어야 전송을 시도한다.
없으면 False를 반환하고 아무것도 하지 않는다 (시스템은 텔레그램 없이 완전 동작).
설정 방법은 README 부록 참조.
"""

from __future__ import annotations

import json
import os
import urllib.request

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured() -> bool:
    """토큰과 챗 ID가 모두 설정돼 있는지."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")) and bool(os.environ.get("TELEGRAM_CHAT_ID"))


def send_message(text: str, timeout: float = 10.0) -> bool:
    """설정돼 있으면 텔레그램으로 텍스트를 전송한다. 미설정/실패 시 False."""
    if not is_configured():
        return False
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        API_URL.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https 고정)
            return 200 <= resp.status < 300
    except OSError:
        return False
