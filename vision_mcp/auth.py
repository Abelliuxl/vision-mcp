"""Authorization check for incoming MCP requests.

Compares the Bearer token from the ``Authorization`` header against the
configured token using constant-time comparison, so that response latencies do
not leak whether a given prefix of the token is correct.
"""

from __future__ import annotations

import hmac

BEARER_PREFIX = "Bearer "


def check_authorization(header_value: str | None, expected_token: str) -> bool:
    """Return True iff ``header_value`` carries exactly ``Bearer <expected_token>``.

    ``header_value`` may be ``None``. ``expected_token`` should be the
    server-side token. Comparison is performed with ``hmac.compare_digest``.
    """
    if not header_value:
        return False
    if not header_value.startswith(BEARER_PREFIX):
        return False
    if not expected_token:
        return False
    if len(header_value) - len(BEARER_PREFIX) != len(expected_token):
        # Length mismatch: still compare against the empty suffix to keep timing
        # roughly constant, then return False.
        hmac.compare_digest(header_value, header_value)
        return False
    presented = header_value[len(BEARER_PREFIX):]
    return hmac.compare_digest(presented, expected_token)
