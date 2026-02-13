"""
Sentry 이벤트를 두 DSN(프로젝트)으로 동시 전송하는 Transport.
멤버 초대 없이 두 계정이 각자 프로젝트에서 알림을 받을 수 있게 함.
두 번째 DSN은 .env의 SENTRY_DSN_EXTRA에만 둡니다 (코드에 노출 X).
"""

import os

from sentry_sdk.transport import HttpTransport, Transport, make_transport


def _get_dsn_extra():
    """환경 변수 SENTRY_DSN_EXTRA만 사용. .env에 없으면 두 번째 전송 안 함."""
    return os.getenv("SENTRY_DSN_EXTRA", "").strip()


class DualDsnsTransport(Transport):
    """동일한 이벤트를 두 Sentry DSN으로 전송하는 Transport."""

    def __init__(self, options):
        super().__init__(options)
        dsn_extra = _get_dsn_extra()
        # 자식은 HttpTransport만 사용 (DualDsnsTransport 쓰면 무한 재귀)
        options_primary = dict(options, transport=HttpTransport)
        t1 = make_transport(options_primary)
        self._transports = [t1] if t1 is not None else []
        if dsn_extra:
            options_extra = dict(options, dsn=dsn_extra, transport=HttpTransport)
            t2 = make_transport(options_extra)
            if t2 is not None:
                self._transports.append(t2)

    def capture_envelope(self, envelope):
        for t in self._transports:
            t.capture_envelope(envelope)

    def flush(self, timeout=None, callback=None):
        for t in self._transports:
            t.flush(timeout=timeout, callback=callback)

    def kill(self):
        for t in self._transports:
            t.kill()
