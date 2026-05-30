"""Shared fixtures. Black-box: drive via subprocess, observe via CLI + filesystem."""

from __future__ import annotations

import json
import subprocess

import pytest


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Isolated vault + XDG dirs for one test. Returns vault Path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    v = tmp_path / "vault"
    v.mkdir()
    subprocess.run(
        ["tephra", "config", "vault", str(v)],
        capture_output=True,
        text=True,
        check=True,
    )
    return v


@pytest.fixture
def run(vault):
    """Subprocess runner. Returns CompletedProcess."""
    def _run(*args, stdin=None):
        return subprocess.run(
            ["tephra", *args],
            capture_output=True,
            text=True,
            input=stdin,
        )
    return _run


@pytest.fixture
def topic(run):
    """Pre-created topic 'Notes' in vault root. Returns name."""
    run("topic", "add", "Notes")
    return "Notes"


@pytest.fixture
def last_json(run):
    """Return a callable that parses `last --json` output."""
    def _last(topic_name=None):
        args = ["last", "--json"]
        if topic_name:
            args += ["-T", topic_name]
        r = run(*args)
        return json.loads(r.stdout)
    return _last


@pytest.fixture
def find_json(run):
    """Return a callable that parses `find --json` output."""
    def _find(*terms, **flags):
        args = ["find", *terms, "--json"]
        for k, v in flags.items():
            args += [f"--{k.replace('_', '-')}", str(v)]
        r = run(*args)
        return json.loads(r.stdout)
    return _find
