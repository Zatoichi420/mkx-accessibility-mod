"""Speaker's fallback rules, with fake voices (no NVDA or SAPI needed)."""

import pytest

from game_a11y_core import speech
from game_a11y_core.speech import Speaker


class FakeVoice:
    def __init__(self, name, available=True, result=True):
        self.name = name
        self.is_available = available
        self.result = result
        self.spoken = []

    def available(self):
        return self.is_available

    def speak(self, text, interrupt):
        self.spoken.append((text, interrupt))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def wait_until_done(self, timeout_seconds):
        pass


@pytest.fixture
def beeps(monkeypatch):
    calls = []
    monkeypatch.setattr(speech, "_audible_alert", lambda: calls.append(1))
    return calls


def make(nvda, sapi, mode="auto", jaws=None):
    jaws = jaws if jaws is not None else FakeVoice("JAWS", available=False)
    created = {"sapi": 0}

    def sapi_factory():
        created["sapi"] += 1
        return sapi

    speaker = Speaker("unused.dll", mode=mode, nvda_factory=lambda _path: nvda, sapi_factory=sapi_factory,
                      jaws_factory=lambda: jaws)
    return speaker, created


def test_uses_nvda_when_running_and_never_starts_sapi(beeps):
    nvda, sapi = FakeVoice("NVDA"), FakeVoice("Windows voice")
    speaker, created = make(nvda, sapi)
    assert speaker.speak("Play")
    assert nvda.spoken == [("Play", True)]
    assert created["sapi"] == 0
    assert beeps == []


def test_falls_back_to_windows_voice_when_nvda_not_running(beeps):
    nvda, sapi = FakeVoice("NVDA", available=False), FakeVoice("Windows voice")
    speaker, _ = make(nvda, sapi)
    assert speaker.speak("Play", interrupt=False)
    assert sapi.spoken == [("Play", False)]
    assert speaker.active_backend_name() == "Windows voice"


def test_falls_back_when_nvda_rejects_the_text(beeps):
    nvda, sapi = FakeVoice("NVDA", result=False), FakeVoice("Windows voice")
    speaker, _ = make(nvda, sapi)
    assert speaker.speak("Play")
    assert nvda.spoken and sapi.spoken


def test_falls_back_when_nvda_raises(beeps):
    nvda, sapi = FakeVoice("NVDA", result=OSError("rpc gone")), FakeVoice("Windows voice")
    speaker, _ = make(nvda, sapi)
    assert speaker.speak("Play")
    assert sapi.spoken == [("Play", True)]


def test_returns_to_nvda_when_it_starts_again(beeps):
    nvda, sapi = FakeVoice("NVDA", available=False), FakeVoice("Windows voice")
    speaker, _ = make(nvda, sapi)
    speaker.speak("one")
    nvda.is_available = True
    speaker.speak("two")
    assert sapi.spoken == [("one", True)]
    assert nvda.spoken == [("two", True)]
    assert speaker.current is nvda


def test_no_voice_at_all_beeps_rate_limited(beeps):
    nvda, sapi = FakeVoice("NVDA", available=False), FakeVoice("Windows voice", available=False)
    speaker, _ = make(nvda, sapi)
    results = [speaker.speak("x") for _ in range(12)]
    assert results == [False] * 12
    assert len(beeps) == 2  # first failure and tenth, not every call
    assert speaker.active_backend_name() is None


def test_recovers_after_failures(beeps):
    nvda, sapi = FakeVoice("NVDA", available=False), FakeVoice("Windows voice", available=False)
    speaker, _ = make(nvda, sapi)
    speaker.speak("x")
    sapi.is_available = True
    assert speaker.speak("y")
    assert speaker.consecutive_failures == 0


def test_mode_none_only_logs(capsys, beeps):
    speaker = Speaker("unused.dll", mode="none",
                      nvda_factory=lambda _p: pytest.fail("NVDA created"),
                      sapi_factory=lambda: pytest.fail("SAPI created"),
                      jaws_factory=lambda: pytest.fail("JAWS created"))
    assert speaker.speak("Game window found.")
    assert "SPEAK: Game window found." in capsys.readouterr().out


def test_mode_nvda_never_uses_windows_voice(beeps):
    nvda, sapi = FakeVoice("NVDA", available=False), FakeVoice("Windows voice")
    speaker, created = make(nvda, sapi, mode="nvda")
    assert not speaker.speak("x")
    assert created["sapi"] == 0


def test_mode_sapi_skips_nvda(beeps):
    speaker = Speaker("unused.dll", mode="sapi",
                      nvda_factory=lambda _p: pytest.fail("NVDA created"),
                      sapi_factory=lambda: FakeVoice("Windows voice"),
                      jaws_factory=lambda: pytest.fail("JAWS created"))
    assert speaker.speak("x")


def test_rejects_unknown_mode():
    with pytest.raises(ValueError):
        Speaker("unused.dll", mode="narrator")


def test_missing_nvda_dll_disables_nvda_instead_of_crashing(tmp_path):
    backend = speech.NvdaBackend(str(tmp_path / "missing.dll"))
    assert backend.available() is False


# --- JAWS (added 2026-10-11) ------------------------------------------------

def test_uses_jaws_when_nvda_not_running_and_never_starts_sapi(beeps):
    nvda, jaws, sapi = FakeVoice("NVDA", available=False), FakeVoice("JAWS"), FakeVoice("Windows voice")
    speaker, created = make(nvda, sapi, jaws=jaws)
    assert speaker.speak("Play")
    assert jaws.spoken == [("Play", True)]
    assert created["sapi"] == 0
    assert speaker.active_backend_name() == "JAWS"
    assert speaker.using_screen_reader()


def test_nvda_wins_when_both_screen_readers_run(beeps):
    nvda, jaws, sapi = FakeVoice("NVDA"), FakeVoice("JAWS"), FakeVoice("Windows voice")
    speaker, _ = make(nvda, sapi, jaws=jaws)
    speaker.speak("Play")
    assert nvda.spoken and not jaws.spoken


def test_falls_back_from_jaws_to_windows_voice_when_jaws_fails(beeps):
    nvda = FakeVoice("NVDA", available=False)
    jaws = FakeVoice("JAWS", result=OSError("COM gone"))
    sapi = FakeVoice("Windows voice")
    speaker, _ = make(nvda, sapi, jaws=jaws)
    assert speaker.speak("Play")
    assert sapi.spoken == [("Play", True)]
    assert not speaker.using_screen_reader()


def test_mode_jaws_never_uses_nvda_or_windows_voice(beeps):
    jaws = FakeVoice("JAWS", available=False)
    speaker = Speaker("unused.dll", mode="jaws",
                      nvda_factory=lambda _p: pytest.fail("NVDA created"),
                      sapi_factory=lambda: pytest.fail("SAPI created"),
                      jaws_factory=lambda: jaws)
    assert not speaker.speak("x")


class FakeJawsApi:
    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def SayString(self, text, flush):
        self.calls.append((text, flush))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_jaws_backend_passes_interrupt_as_flush():
    api = FakeJawsApi()
    backend = speech.JawsBackend(is_running=lambda: True, connect=lambda: api)
    assert backend.available()
    assert backend.speak("Play", interrupt=True) is True
    assert backend.speak("Versus", interrupt=False) is True
    assert api.calls == [("Play", True), ("Versus", False)]


def test_jaws_backend_unavailable_when_jaws_not_running():
    backend = speech.JawsBackend(is_running=lambda: False,
                                 connect=lambda: pytest.fail("connected without JAWS running"))
    assert backend.available() is False


def test_jaws_backend_reconnects_after_jaws_restarts():
    running = {"value": True}
    apis = []

    def connect():
        apis.append(FakeJawsApi())
        return apis[-1]

    backend = speech.JawsBackend(is_running=lambda: running["value"], connect=connect)
    assert backend.available()
    running["value"] = False
    assert not backend.available()
    running["value"] = True
    assert backend.available()
    assert len(apis) == 2


def test_jaws_backend_drops_broken_connection():
    calls = {"n": 0}

    def connect():
        calls["n"] += 1
        return FakeJawsApi(result=OSError("RPC server unavailable") if calls["n"] == 1 else True)

    backend = speech.JawsBackend(is_running=lambda: True, connect=connect)
    assert backend.available()
    with pytest.raises(OSError):
        backend.speak("x", True)
    assert backend.available()  # reconnects
    assert backend.speak("y", True) is True
    assert calls["n"] == 2


def test_jaws_backend_unreachable_api_is_unavailable_not_fatal(capsys):
    def connect():
        raise OSError("class not registered")

    backend = speech.JawsBackend(is_running=lambda: True, connect=connect)
    assert backend.available() is False
    assert backend.available() is False
    assert capsys.readouterr().out.count("couldn't be reached") == 1  # logged once
