import os
import signal
import subprocess
import sys
from concurrent.futures import Future
from pathlib import Path

import pytest

import mellea_skills_compiler.cli as cli
from mellea_skills_compiler.certification import pipeline
from mellea_skills_compiler.certification.exceptions import CertificationInterrupted
from mellea_skills_compiler.models import Fixture


def test_fixture_interrupt_cancels_pending_work_without_waiting(monkeypatch):
    future = Future()

    class FakeExecutor:
        def __init__(self):
            self.shutdown_calls = []

        def submit(self, *args, **kwargs):
            return future

        def shutdown(self, wait=True, cancel_futures=False):
            self.shutdown_calls.append((wait, cancel_futures))

    executor = FakeExecutor()
    monkeypatch.setattr(pipeline, "ThreadPoolExecutor", lambda: executor)
    monkeypatch.setattr(pipeline, "as_completed", lambda **kwargs: iter([future]))
    monkeypatch.setattr(
        future,
        "result",
        lambda: (_ for _ in ()).throw(CertificationInterrupted(signal.SIGINT)),
    )

    with pytest.raises(CertificationInterrupted):
        pipeline._run_fixtures(
            lambda: None,
            [Fixture(id="interrupt", context={}, description="interrupt run")],
        )

    assert future.cancelled()
    assert executor.shutdown_calls == [(False, True)]


def test_certify_ignores_repeated_signals_and_flushes_before_exit(monkeypatch):
    events = []

    class FlushProbe:
        def __init__(self, name, signal_to_raise=None):
            self.name = name
            self.signal_to_raise = signal_to_raise

        def flush(self):
            events.append(self.name)
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
            if self.signal_to_raise is not None:
                signal.raise_signal(self.signal_to_raise)

    def interrupted_pipeline(**kwargs):
        raise CertificationInterrupted(signal.SIGINT)

    monkeypatch.setattr(pipeline, "full_pipeline", interrupted_pipeline)
    monkeypatch.setattr(cli.sys, "stdout", FlushProbe("stdout", signal.SIGTERM))
    monkeypatch.setattr(cli.sys, "stderr", FlushProbe("stderr"))
    monkeypatch.setattr(cli.logging, "shutdown", lambda: events.append("logging"))
    monkeypatch.setattr(cli.os, "_exit", lambda code: events.append(("exit", code)))

    cli.certify(None, "unused", inference_engine="OLLAMA")

    assert events == ["stdout", "stderr", "logging", ("exit", 128 + signal.SIGINT)]


def test_fixture_results_are_returned_on_normal_completion():
    fixture = Fixture(id="normal", context={}, description="normal run")

    results = pipeline._run_fixtures(lambda: "completed", [fixture])

    assert len(results) == 1
    assert results[0].fixture is fixture
    assert results[0].status == "success"
    assert results[0].output == "completed"


@pytest.mark.parametrize("signal_number", [signal.SIGINT, signal.SIGTERM])
def test_certify_signal_exits_promptly_with_signal_status(signal_number):
    source_root = Path(__file__).resolve().parents[3]
    script = f"""
import signal
import threading
import time
from types import SimpleNamespace
import mellea_skills_compiler.certification.pipeline as pipeline
import mellea_skills_compiler.cli as cli

def fake_full_pipeline(**kwargs):
    fixture_started = threading.Event()

    def run_fixture(value):
        fixture_started.set()
        time.sleep(30)

    def send_signal():
        if not fixture_started.wait(timeout=2):
            raise AssertionError("fixture worker did not start")
        signal.raise_signal({signal_number})

    assert signal.getsignal({signal_number}) is cli._certification_signal_handler
    timer = threading.Timer(0.5, send_signal)
    timer.daemon = True
    timer.start()
    fixture = SimpleNamespace(context=None)
    return pipeline._run_fixtures(run_fixture, [fixture])

pipeline.full_pipeline = fake_full_pipeline
cli.certify(None, "unused", inference_engine="OLLAMA")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(source_root / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=source_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert (
        result.returncode == 128 + signal_number
    ), f"stdout={result.stdout!r}; stderr={result.stderr!r}"
