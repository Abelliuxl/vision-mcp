# tests/test_auth.py
import time
from vision_mcp.auth import check_authorization, BEARER_PREFIX


def test_check_accepts_correct_bearer():
    assert check_authorization("Bearer secret-token-123", "secret-token-123") is True


def test_check_rejects_wrong_token():
    assert check_authorization("Bearer wrong-token", "secret-token-123") is False


def test_check_rejects_missing_header():
    assert check_authorization(None, "secret-token-123") is False


def test_check_rejects_wrong_scheme():
    assert check_authorization("Basic dXNlcjpwYXNz", "secret-token-123") is False


def test_check_is_case_sensitive():
    assert check_authorization("bearer secret-token-123", "secret-token-123") is False
    assert check_authorization("Bearer SECRET-TOKEN-123", "secret-token-123") is False


def test_check_rejects_empty_token():
    assert check_authorization("Bearer ", "") is False


def test_check_rejects_token_with_extra_space():
    # We require exactly one space after "Bearer"; extra space is rejected.
    assert check_authorization("Bearer  token-with-double-space", "token-with-double-space") is False


def test_timing_safety_enough(monkeypatch):
    """Compare wall time of correct vs wrong token; difference bounded."""
    real = "x" * 64
    wrong = "y" * 64
    repeats = 5000

    t0 = time.perf_counter()
    for _ in range(repeats):
        check_authorization(f"Bearer {real}", real)
    t_correct = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(repeats):
        check_authorization(f"Bearer {wrong}", real)
    t_wrong = time.perf_counter() - t0

    # Allow up to 5x slower; far below constant-time guarantee but catches gross regressions.
    ratio = max(t_correct, t_wrong) / min(t_correct, t_wrong)
    assert ratio < 5.0, f"timing ratio {ratio:.2f} suggests non-constant-time comparison"
