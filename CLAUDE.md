# CLAUDE.md

SUSA (SUSA Unified Systems API) is a Python library for programmatically working with machines, currently centered
around libvirt/QEMU virtual machines of many architectures.

## Commands

- `uv sync`, `uv run ruff check`, `uv run ruff format`, `uv run mypy` (strict).
- What CI runs: `uv run pre-commit run --all-files`.
- Fast tests: `uv run pytest --ignore tests/libvirt/test_machine.py`.
- Update XML snapshots after an intended model change: `uv run pytest tests/libvirt/test_models.py --snapshot-update`,
  then re-run without the flag and review the diff.
- Real-VM tests: `uv run pytest tests/libvirt/test_machine.py -n 3` (more workers starve the host and time out).

## Design

- **Layers.** `susa.core` holds backend-independent contracts (abstract classes) only. `susa.libvirt` implements them,
  `susa.communicator` runs commands over any stream, `susa.recipes` makes objects from JSON, and `susa.utilities` holds
  general helpers.
- **Bottom up.** Parts are small and independent (models, entities, communicators), each can be a JSON recipe, and they
  connect directly (e.g. `machine.network(network)`, `SSHCommunicator(machine, ...)`, `{"$ref": "machine"}`).
  Conveniences are opt-in, generic and composable (e.g. `Session`); nothing imposes a layout or an orchestration.
- **Let the libraries do it.** Prefer what libvirt (or another library) already provides. SUSA doesn't implement what
  no library does, and doesn't reach behind its backend's back.
- **Capabilities are mixins** (`Snapshottable`, `Powerable`, ...), checked with `isinstance`.
- **Contracts stay loose.** Core types are ABCs with abstract properties; don't collapse them into concrete classes.
- **Resources.** Anything with a lifetime is a `Resource` (`create()`/`destroy()`, a context manager). Factory methods
  return resources that aren't created yet.
- **Models are values, entities are live.** Models build libvirt XML with chainable builders returning `Self`, and
  `get_*()` getters. Builder methods and constructor parameters are the recipe format, so keep them JSON-friendly.
- **Workarounds stay where they're needed**, with a comment saying why, never in general helpers. Bugs in a dependency
  we own (e.g. `pydantic-libvirt`) get fixed there.

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
