from __future__ import annotations

from collections.abc import Sequence

import pytest
from typing_extensions import override

from susa.core.keyboard import Key, type_text
from susa.core.machine import KeyPressable


class FakeKeyboard(KeyPressable):
    def __init__(self) -> None:
        self.presses: list[list[Key]] = []

    @override
    def press(self, keys: Sequence[Key], hold_time: float = 0.1) -> None:
        self.presses.append(list(keys))


def test_type_text() -> None:
    keyboard = FakeKeyboard()
    type_text(keyboard, "aZ5% _\n\t~")
    assert keyboard.presses == [
        [Key.A],
        [Key.LEFT_SHIFT, Key.Z],
        [Key.DIGIT_5],
        [Key.LEFT_SHIFT, Key.DIGIT_5],
        [Key.SPACE],
        [Key.LEFT_SHIFT, Key.MINUS],
        [Key.ENTER],
        [Key.TAB],
        [Key.LEFT_SHIFT, Key.GRAVE],
    ]


def test_type_text_everything_printable() -> None:
    type_text(FakeKeyboard(), "".join(map(chr, range(32, 127))))


def test_type_text_unsupported() -> None:
    with pytest.raises(ValueError, match="é"):
        type_text(FakeKeyboard(), "é")
