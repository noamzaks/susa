from __future__ import annotations

from collections.abc import Sequence

import pytest
from typing_extensions import override

from susa.core.keyboard import Key, KeyPressable


class FakeKeyboard(KeyPressable):
    def __init__(self) -> None:
        self.presses: list[list[Key]] = []

    @override
    def press(self, keys: Sequence[Key], hold_time: float = 0.1) -> None:
        self.presses.append(list(keys))


def test_type_text() -> None:
    keyboard = FakeKeyboard()
    keyboard.type_text("aZ5% _\n\t~")
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
    FakeKeyboard().type_text("".join(map(chr, range(32, 127))))


def test_type_text_unsupported() -> None:
    keyboard = FakeKeyboard()
    with pytest.raises(ValueError, match="é"):
        keyboard.type_text("abcé")
    # Nothing was typed.
    assert keyboard.presses == []
