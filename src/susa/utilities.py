import platform
import random
import string

KILO = 1 << 10
MEGA = KILO << 10
GIGA = MEGA << 10


def random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def host_arch() -> str:
    machine = platform.machine()
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine in ("x86_64", "amd64", "AMD64"):
        return "x86_64"
    raise ValueError(f"Unknown host architecture: {machine!r}")
