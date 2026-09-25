import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def tmp_dir_path() -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        p.chmod(0o777)
        yield p
