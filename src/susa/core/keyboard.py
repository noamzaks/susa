from __future__ import annotations

import string
from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import Enum

from typing_extensions import override

from susa.core.stream import InputStream


class Key(Enum):
    # Values are Linux input event codes.
    ESCAPE = 1
    DIGIT_1 = 2
    DIGIT_2 = 3
    DIGIT_3 = 4
    DIGIT_4 = 5
    DIGIT_5 = 6
    DIGIT_6 = 7
    DIGIT_7 = 8
    DIGIT_8 = 9
    DIGIT_9 = 10
    DIGIT_0 = 11
    MINUS = 12
    EQUAL = 13
    BACKSPACE = 14
    TAB = 15
    Q = 16
    W = 17
    E = 18
    R = 19
    T = 20
    Y = 21
    U = 22
    I = 23
    O = 24
    P = 25
    LEFT_BRACKET = 26
    RIGHT_BRACKET = 27
    ENTER = 28
    LEFT_CTRL = 29
    A = 30
    S = 31
    D = 32
    F = 33
    G = 34
    H = 35
    J = 36
    K = 37
    L = 38
    SEMICOLON = 39
    APOSTROPHE = 40
    GRAVE = 41
    LEFT_SHIFT = 42
    BACKSLASH = 43
    Z = 44
    X = 45
    C = 46
    V = 47
    B = 48
    N = 49
    M = 50
    COMMA = 51
    DOT = 52
    SLASH = 53
    RIGHT_SHIFT = 54
    KEYPAD_ASTERISK = 55
    LEFT_ALT = 56
    SPACE = 57
    CAPS_LOCK = 58
    F1 = 59
    F2 = 60
    F3 = 61
    F4 = 62
    F5 = 63
    F6 = 64
    F7 = 65
    F8 = 66
    F9 = 67
    F10 = 68
    NUM_LOCK = 69
    SCROLL_LOCK = 70
    KEYPAD_7 = 71
    KEYPAD_8 = 72
    KEYPAD_9 = 73
    KEYPAD_MINUS = 74
    KEYPAD_4 = 75
    KEYPAD_5 = 76
    KEYPAD_6 = 77
    KEYPAD_PLUS = 78
    KEYPAD_1 = 79
    KEYPAD_2 = 80
    KEYPAD_3 = 81
    KEYPAD_0 = 82
    KEYPAD_DOT = 83
    F11 = 87
    F12 = 88
    KEYPAD_ENTER = 96
    RIGHT_CTRL = 97
    KEYPAD_SLASH = 98
    SYSRQ = 99
    RIGHT_ALT = 100
    HOME = 102
    UP = 103
    PAGE_UP = 104
    LEFT = 105
    RIGHT = 106
    END = 107
    DOWN = 108
    PAGE_DOWN = 109
    INSERT = 110
    DELETE = 111
    PAUSE = 119
    LEFT_META = 125
    RIGHT_META = 126
    MENU = 127


# A US keyboard.
UNSHIFTED: dict[str, Key] = {
    **{c: Key[c.upper()] for c in string.ascii_lowercase},
    **{d: Key[f"DIGIT_{d}"] for d in string.digits},
    "-": Key.MINUS,
    "=": Key.EQUAL,
    "[": Key.LEFT_BRACKET,
    "]": Key.RIGHT_BRACKET,
    "\\": Key.BACKSLASH,
    ";": Key.SEMICOLON,
    "'": Key.APOSTROPHE,
    "`": Key.GRAVE,
    ",": Key.COMMA,
    ".": Key.DOT,
    "/": Key.SLASH,
    " ": Key.SPACE,
    "\n": Key.ENTER,
    "\r": Key.ENTER,
    "\t": Key.TAB,
    "\b": Key.BACKSPACE,
    "\x1b": Key.ESCAPE,
}
# Each character typed with shift, and the one typed without it on the same key.
SHIFTED: dict[str, str] = {
    **{c.upper(): c for c in string.ascii_lowercase},
    **dict(zip(")!@#$%^&*(", string.digits)),
    **dict(zip('_+{}|:"~<>?', "-=[]\\;'`,./")),
}
KEYS: dict[str, list[Key]] = {
    **{c: [key] for c, key in UNSHIFTED.items()},
    **{c: [Key.LEFT_SHIFT, UNSHIFTED[u]] for c, u in SHIFTED.items()},
}


class KeyPressable(ABC):
    @abstractmethod
    def press(self, keys: Sequence[Key], hold_time: float = 0.1) -> None: ...

    def type_text(self, text: str, hold_time: float = 0.05) -> None:
        for c in text:
            if c not in KEYS:
                raise ValueError(f"Can't type {c!r}")
            self.press(KEYS[c], hold_time)


class KeyPressableInputStream(InputStream):
    def __init__(self, machine: KeyPressable) -> None:
        self.machine = machine

    @override
    def write(self, data: bytes) -> None:
        self.machine.type_text(data.decode())

    @override
    def close(self) -> None:
        pass
