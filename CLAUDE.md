# CLAUDE.md

SUSA (SUSA Unified Systems API) is a Python library for programmatically working with machines, currently centered
around libvirt/QEMU virtual machines of many architectures.

## Commands

- `uv sync`, `uv run ruff check`, `uv run ruff format`, `uv run mypy` (strict).
- What CI runs: `uv run pre-commit run --all-files`.
- Always run tests with `scripts/test.sh` (pytest's arguments), which records each run for greendots in
  `/var/opt/greendots2/susa/<commit>-<n>` (the `susa` project).
- Fast tests: `scripts/test.sh --ignore tests/libvirt/test_machine.py --ignore tests/podman`.
- Update XML snapshots after an intended model change: `scripts/test.sh tests/libvirt/test_models.py --snapshot-update`,
  then re-run without the flag and review the diff.
- Real-VM tests: `scripts/test.sh tests/libvirt/test_machine.py -n 3` (more workers starve the host and time out), and
  `scripts/test.sh tests/podman` (builds the container's image the first time).

## Design

- **Layers.** `susa.core` holds backend-independent contracts (abstract classes) only. `susa.libvirt` implements them,
  `susa.communicators` runs commands over any stream, `susa.podman` runs libvirt in a container, `susa.recipes` makes
  objects from JSON, and `susa.utilities` holds general helpers. Each is its own distribution in the uv workspace under
  `packages/` (`susa-core` holds core and utilities), sharing the `susa` namespace package (so there's no
  `susa/__init__.py`), and depends only on those below it: core, then communicators and libvirt, then podman, then
  recipes.
- **Bottom up.** Parts are small and independent (models, entities, communicators), each can be a JSON recipe, and they
  connect directly (e.g. `machine.network(network)`, `SSHCommunicator(machine, ...)`, `{"$ref": "machine"}`).
  Conveniences are opt-in, generic and composable (e.g. `Session`); nothing imposes a layout or an orchestration.
- **Let the libraries do it.** Prefer what libvirt (or another library) already provides. SUSA doesn't implement what
  no library does, and doesn't reach behind its backend's back.
- **Plain and simple.** Each function does one simple thing. Use libraries through their high-level APIs (e.g. pydantic
  models, not core schemas). No machinery nothing needs (e.g. serialization, cross-process coordination, sharing a
  resource between concurrent users).
- **Capabilities are mixins** (`Snapshottable`, `Powerable`, ...), checked with `isinstance`.
- **Contracts stay loose.** Core types are ABCs with abstract properties; don't collapse them into concrete classes.
- **Defaults are `Variable`s** (e.g. `HOST`, which commands run on, and `Connection.URI`), taken when an object is made,
  and set for a `with` block. Their initial values may come from the environment (e.g. `HOST` from the `host` of the
  `SUSA_SESSION` recipe, see `susa.utilities.environment`), which is how `LibvirtContainer` passes its defaults on to
  processes started meanwhile; code otherwise never reads `os.environ`.
- **Resources.** Anything with a lifetime is a `Resource` (`create()`/`destroy()`, a context manager). Factory methods
  return resources that aren't created yet.
- **Models are values, entities are live.** Models build libvirt XML with chainable builders returning `Self`, and
  `get_*()` getters. Builder methods and constructor parameters are the recipe format, so keep them JSON-friendly.
- **Workarounds stay where they're needed**, with a comment saying why, never in general helpers. Bugs in a dependency
  we own (e.g. `pytest-greendots`) get fixed there.

## Conventions

- Keep code minimal and succinct:
  - No docstrings; abstract methods are just `...`.
  - Comments only where something really isn't clear from the code.
  - Prefer simple code over defensive code. No try/except or fallbacks for cases that shouldn't happen; use `assert`
    sanity checks instead. Never rely on an `assert` for a side effect.
  - Return early (`if not ...: return`) rather than wrapping the rest of a function in an `if`.
  - Remove API that isn't used.
- Class layout, in groups of related methods:
  - Models: `__init__`, builders that set things, builders that add devices, builders taking other models, `default*`,
    helpers, then `get_*` getters.
  - Other classes: `__init__`, properties, the lifecycle (`create`/`destroy`/`lookup`), each capability's methods
    together (in the order of the bases), then serialization and helpers.
- Log with the `logging` module's functions directly, not per-module loggers.
- `# type: ignore` without error codes.
- Optional/heavy dependencies (e.g. `PIL`, `scapy`) are imported lazily, with `TYPE_CHECKING` imports for annotations.
- Code must run on Python 3.10:
  - Every module starts with `from __future__ import annotations`.
  - Generics use `TypeVar`/`Generic`, not PEP 695; type aliases use `TypeAlias`.
  - `Self` and `override` come from `typing_extensions`.
- Mark every overriding method with `@override` (mypy's `explicit-override` is on).
