from __future__ import annotations

import pytest

from susa.utilities.generic import Deadline


def test_deadline_test() -> None:
    Deadline(None).test("Not reached")
    Deadline(60).test("Not reached")
    with pytest.raises(TimeoutError, match="^It didn't happen within 0 seconds$"):
        Deadline(0).test("It didn't happen")
