from __future__ import annotations

import logging
import re
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import cast

import pytest

from susa.core.resource import Resource
from susa.libvirt.state import LVState

FAILED = pytest.StashKey[bool]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--save-failed",
        type=Path,
        metavar="DIRECTORY",
        help="Where save_if_failed saves the libvirt state of failed tests",
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if report.when == "call" and report.failed:
        item.stash[FAILED] = True
    return report


# Called by a fixture's teardown, after its test ran.
@pytest.fixture
def save_if_failed(
    request: pytest.FixtureRequest,
) -> Callable[[Sequence[Resource]], None]:
    def save(resources: Sequence[Resource]) -> None:
        # pytest doesn't annotate it.
        item = cast("pytest.Item", request.node)  # pyright: ignore
        directory: Path | None = request.config.getoption("save_failed")
        if directory is None or not item.stash.get(FAILED, False):
            return
        path = directory / re.sub(r"[^\w.\[\]-]+", "_", item.nodeid)
        logging.info("Saving the failed state in %s", path)
        LVState.save(resources, path)

    return save
