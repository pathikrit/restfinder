import signal

import pytest

from restfinder import dev


def test_available_port_does_not_prompt(monkeypatch):
    monkeypatch.setattr(dev, "port_is_available", lambda port: True)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("unexpected prompt"))

    dev.ensure_port_available(8080)


def test_occupied_port_can_be_left_running(monkeypatch):
    monkeypatch.setattr(dev, "port_is_available", lambda port: False)
    monkeypatch.setattr(dev, "listener_pids", lambda port: [123])
    monkeypatch.setattr(dev, "process_descriptions", lambda pids: "123 python server.py")
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    monkeypatch.setattr(dev.os, "kill", lambda pid, sig: pytest.fail("unexpected kill"))

    with pytest.raises(SystemExit, match="not started"):
        dev.ensure_port_available(8080)


def test_occupied_port_is_terminated_after_confirmation(monkeypatch):
    availability = iter([False, True])
    killed = []
    monkeypatch.setattr(dev, "port_is_available", lambda port: next(availability))
    monkeypatch.setattr(dev, "listener_pids", lambda port: [123])
    monkeypatch.setattr(dev, "process_descriptions", lambda pids: "123 python server.py")
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    monkeypatch.setattr(dev.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    dev.ensure_port_available(8080)

    assert killed == [(123, signal.SIGTERM)]
