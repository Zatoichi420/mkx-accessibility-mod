"""Single-instance mutex and --stop event. Windows kernel objects, so
Windows only (CI runs these on windows-latest)."""

import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel objects")


def _name(kind):
    return f"Local\\MKXAccessTest.{kind}.{uuid.uuid4().hex}"


def test_mutex_allows_exactly_one_owner():
    from game_a11y_core.lifecycle import acquire_named_mutex, close_handle, named_mutex_exists

    name = _name("Mutex")
    assert not named_mutex_exists(name)
    first = acquire_named_mutex(name)
    assert first
    assert named_mutex_exists(name)
    assert acquire_named_mutex(name) is None
    close_handle(first)
    assert not named_mutex_exists(name)
    again = acquire_named_mutex(name)
    assert again
    close_handle(again)


def test_stop_event_round_trip():
    from game_a11y_core.lifecycle import close_handle, create_stop_event, signal_stop_event, wait_for_event

    name = _name("Stop")
    assert signal_stop_event(name) is False  # nobody listening yet
    event = create_stop_event(name)
    try:
        assert wait_for_event(event, 0) is False
        assert signal_stop_event(name) is True
        assert wait_for_event(event, 0) is True
        assert wait_for_event(event, 0) is True  # manual reset: stays signalled
    finally:
        close_handle(event)


def test_new_stop_event_clears_a_stale_signal():
    from game_a11y_core.lifecycle import close_handle, create_stop_event, signal_stop_event, wait_for_event

    name = _name("Stale")
    holder = create_stop_event(name)
    try:
        signal_stop_event(name)
        fresh = create_stop_event(name)  # a reader starting while the old object still exists
        try:
            assert wait_for_event(fresh, 0) is False
        finally:
            close_handle(fresh)
    finally:
        close_handle(holder)
