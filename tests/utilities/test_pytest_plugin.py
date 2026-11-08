from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


def test_save_if_failed(pytester: pytest.Pytester, tmp_path: Path) -> None:
    pytester.makepyfile(
        """
import pytest
from tests.core.test_saveable import Thing

@pytest.fixture
def thing(save_if_failed):
    yield
    save_if_failed([Thing("thing")])

def test_fails(thing):
    assert False

def test_passes(thing):
    pass
"""
    )
    pytester.runpytest(f"--save-failed={tmp_path}").assert_outcomes(passed=1, failed=1)
    [path] = tmp_path.iterdir()
    assert path.name == "test_save_if_failed.py_test_fails.json"
    assert json.loads(path.read_text()) == [
        {
            "resource": {"type": "tests.core.test_saveable:Thing", "state": "thing"},
            "state": None,
        }
    ]
