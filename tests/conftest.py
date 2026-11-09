from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest

from susa.podman.container import LibvirtContainer


@pytest.fixture(scope="module")
def libvirt() -> Iterator[LibvirtContainer]:
    if shutil.which("podman") is None:
        pytest.skip("Needs podman")
    with LibvirtContainer() as container:
        yield container
