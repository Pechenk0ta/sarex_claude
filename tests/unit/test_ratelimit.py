from app.auth.ratelimit import LoginLimiter


def test_blocks_after_five_failures_and_unblocks_after_window() -> None:
    limiter = LoginLimiter(max_failures=5, window_seconds=900)
    keys = ["email:a@example.ru", "ip:1.2.3.4"]
    for second in range(5):
        assert limiter.blocked_for(keys, now=second) == 0
        limiter.failed(keys, now=second)
    assert limiter.blocked_for(keys, now=10) > 0
    assert limiter.blocked_for(keys, now=901) == 0  # the first failure left the window


def test_success_resets_counter() -> None:
    limiter = LoginLimiter(max_failures=2)
    keys = ["email:a@example.ru"]
    limiter.failed(keys, now=0)
    limiter.succeeded(keys)
    limiter.failed(keys, now=1)
    assert limiter.blocked_for(keys, now=2) == 0


def test_same_ip_is_blocked_for_other_emails() -> None:
    limiter = LoginLimiter(max_failures=3)
    for i in range(3):
        limiter.failed([f"email:user{i}@example.ru", "ip:5.6.7.8"], now=i)
    assert limiter.blocked_for(["email:new@example.ru", "ip:5.6.7.8"], now=5) > 0
