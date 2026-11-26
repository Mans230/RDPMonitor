"""Cooperative deadlines for diagnostics; native subprocess.run enforces timeouts."""
import contextlib
import threading
import time

_CONTEXT = threading.local()


@contextlib.contextmanager
def deadline_scope(seconds):
    previous = getattr(_CONTEXT, "deadline", None)
    deadline = time.monotonic() + max(0, float(seconds))
    _CONTEXT.deadline = min(previous, deadline) if previous is not None else deadline
    try:
        yield
    finally:
        _CONTEXT.deadline = previous


def remaining_timeout(requested=None):
    deadline = getattr(_CONTEXT, "deadline", None)
    if deadline is None:
        return requested
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("diagnostic deadline exceeded")
    return min(float(requested), remaining) if requested is not None else remaining
