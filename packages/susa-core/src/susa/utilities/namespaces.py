from __future__ import annotations

import ctypes
import os
import threading


# Its subprocesses start in them too. A process can only join a user namespace while it has a single thread.
def join_namespaces(pid: int, *kinds: str) -> None:
    assert "user" not in kinds or threading.active_count() == 1, (
        "Join user namespaces before starting threads!"
    )
    # `os.setns` is only in Python 3.12+.
    libc = ctypes.CDLL(None, use_errno=True)
    for kind in kinds:
        namespace = os.open(f"/proc/{pid}/ns/{kind}", os.O_RDONLY)
        result = libc.setns(namespace, 0)
        os.close(namespace)
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, f"Can't join {kind} namespace: {os.strerror(error)}")
