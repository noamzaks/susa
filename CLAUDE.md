# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SUSA (SUSA Unified Systems API) is a Python library for programmatically working with machines. It's in very
early development and currently centered around libvirt/QEMU virtual machines on Linux, across many guest
architectures (x86_64, aarch64, mips, ppc64le, armv7l, riscv64, i686), mostly emulated with TCG.

## Commands

This project uses `uv`. It supports Python 3.10+, and 3.10 is the default (`.python-version`, which CI also
uses), so the default environment catches anything newer.

- Install/sync dependencies: `uv sync` (building `libvirt-python` needs `pkg-config` and the libvirt dev headers)
- Lint / format: `uv run ruff check`, `uv run ruff format`
- Type-check: `uv run mypy` (strict, checks `src` and `tests`, configured in `pyproject.toml`)
- All pre-commit hooks (what CI runs): `uv run pre-commit run --all-files`. The mypy hook is a local hook that runs
  `uv run mypy` in the project environment. The ruff hook's `rev` and the `ruff` dev dependency are pinned to the
  same version; bump them together.
- Fast tests: `uv run pytest --ignore tests/libvirt/test_machine.py`
- Single test: `uv run pytest "tests/libvirt/test_models.py::test_machine_model_default[mips]"`
- Update XML snapshots after an intended model change: `uv run pytest tests/libvirt/test_models.py --snapshot-update`
  (the run reports each rewritten snapshot as an error; re-run without the flag and review the diff under
  `tests/libvirt/snapshots/`)
- Real-VM tests: `uv run pytest tests/libvirt/test_machine.py -n 3` (see [Tests](#tests)). Keep `-n` at about 3: each
  guest has 2 GB, and many TCG guests at once starve the 6-core host and cause timeouts. Don't pass `-p no:xdist`
  (the `--dist loadgroup` addopt needs xdist).
- Release build: `scripts/release.sh` generates the JSON schemas the package ships (`python -m susa.schemas` writes
  the gitignored `src/susa/schemas/<Type>.schema.json` for the models and entities, which `uv_build` still packs) and
  runs `uv build`.

## Design

These shape every part of the code; keep new code in line with them.

- **Layers.** `susa.core` holds the backend-independent contracts (abstract classes) and nothing backend- or
  OS-specific. `susa.libvirt` implements them for libvirt/QEMU, and `susa.communicator` runs commands over any
  stream (a shell over serial, ssh, telnet or rlogin). `susa.utilities` holds general helpers, including the
  pydantic machinery (`recipe`, `serializable`).
- **Capabilities are mixins.** A machine is a `Machine` plus whichever of `Snapshottable`, `Powerable`,
  `Screenshottable`, `SerialAccessible`, `KeyPressable` it supports; networks may be `Sniffable`. Code checks
  capabilities with `isinstance`.
- **Contracts stay loose.** Core types are ABCs with abstract properties (e.g. `Interface` with `mac`/`ip`, which
  `BasicInterface`/`LVInterface` implement as plain values), so backends are free in how they provide them. Don't
  collapse them into concrete classes.
- **Resources.** Anything with a lifetime is a `Resource`: `create()`/`destroy()`, and a context manager. Factory
  methods (`snapshot()`, `serial()`, `sniffer()`) return resources that aren't created yet, to use with `with` (or
  `create()`), and `create()` asserts it runs once. A component given a resource to drive (e.g.
  `SerialCommunicator` and its serial) creates it and destroys it with itself.
- **Models are values, entities are live.** Models (`*_model.py`) build libvirt XML. Entities (`LVMachine`, ...)
  hold a model and the live libvirt object. Both are `Serializable`, so they're pydantic types (and picklable) by
  their serialized form, and models can be written as JSON recipes.
- **Workarounds stay where they're needed**, with a comment saying why: e.g. the `0o777` temp dir is in the VM test
  fixture (QEMU runs as another user), not in a helper. Bugs in a dependency we own (e.g.
  `pydantic-libvirt`) get fixed there rather than worked around here.

## Packages

### `susa.core`

- `Resource`, `Machine` (`name`, `interfaces`, and `ips`/`ip` from them), `Network` (`name`, `interfaces`),
  `Interface` (`mac`, and `ip` when it's known in advance; `BasicInterface` is a plain value).
- `core/machine.py` has the machine capabilities:
  - `Snapshottable`: `snapshot()` returns a `Snapshot`; destroying it reverts the machine and deletes the snapshot.
  - `Powerable`: `is_powered_on`; `power_on`/`power_off`/`reset` are immediate, `shutdown`/`reboot` ask the guest.
  - `Screenshottable`: a `Screenshot` of bytes plus an optional MIME type (`image`/`text` via PIL/tesseract).
  - `SerialAccessible`: `serial()` returns a `Serial`, a `Resource` and an `InputOutputStream`.
- `core/keyboard.py`: `KeyPressable` (`press(keys, hold_time)` holds `Key`s together; `type_text(text)` types
  letters, digits, ASCII symbols, space, `\n`, `\r`, `\t`, `\b` and ESC as on a US keyboard, checking all of it
  first), with `Key` values being Linux input event codes, and `KeyPressableInputStream` (types what's written). An
  `OutputStream` of OCR'd screen text was tried and removed: OCR output jitters between screenshots of the same
  screen, so new text can't be told apart from old without heuristics.
- `core/network.py`: `Sniffable.sniffer()` returns a `Sniffer`, a `Resource` whose output is a pcap stream, with
  `next_packet`/`packets` parsing it into scapy packets (scapy imported lazily).
- `core/stream.py`:
  - `OutputStream`: `read(size, timeout)` returns `b""` on timeout and raises `EOFError` once the stream ended and
    nothing's left; `read_until`, `read_all` (until EOF), `is_quiet`, and `wait_until_quiet`, which never starts a
    quiet period that can't fit before its timeout.
  - `InputStream` (`write`, and `close`, meaning no more input, which ends a stream that can't be half-closed),
    `InputOutputStream`, `BasicInputOutputStream` (an `OutputStream` plus an `InputStream`).
  - `SavedOutputStream` keeps what's read. `PexpectStream` is pexpect's `SpawnBase` over an `OutputStream`
    (`expect`, `before`, `match`); its `read` goes straight to the wrapped stream, so data `expect` read past its
    match stays in its `buffer`.
- `core/communicator.py` (everything is `bytes`):
  - `FileTransferrer`: abstract `upload_single(local, remote)`/`download_single(remote, local)`, and
    `upload({local: remote})`/`download({remote: local})`, which loop over them by default.
  - `CommandRunner` (a `Resource` and a `FileTransferrer`): `run(command) -> CompletedProcess[bytes]`, and `check`,
    which returns stdout and raises `CalledProcessError` on failure.
  - `AsyncCommandRunner`: adds `start(command) -> AsyncCommand` (`stdin`, `stdout`, `stderr` streams, `poll`, `wait`
    returning the exit code, `kill`). Its `run` is `start`, `stdin.close()`, `wait`, then `read_all` of both
    streams (a timeout doesn't kill the command).

### `susa.libvirt`

**Models.** `*_model.py` (`machine_model.py` holds both `MachineModel`, a libvirt domain, and `SnapshotModel`) wrap
the pydantic-xml schemas of the `pydantic-libvirt` package (a git dependency, imported as `lvdomain` / `lvnetwork` /
`lvdomainsnapshot`). Each `Model` holds an `xml_model` and has chainable builder methods returning `Self`
(`MachineModel("x").arch("x86_64").default().memory(...)`), `build()` to XML, `parse(xml)` back, and `get_*()`
getters (the plain names are taken by the builders, e.g. `arch()` vs `get_arch()`). Constructor settings have
builder methods too (`name`, `mac`), so recipes can express them.

**Recipes.** A model is validated (as a pydantic type) from its XML or from a JSON recipe: a list of steps, each
calling a builder method (`susa.utilities.recipe`, generic over any class). A step is `{method: arguments}`, with an
object of arguments by name (`{"efi": {"loader": ..., "nvram": ...}}`) or else just the first argument
(`{"arch": "x86_64"}`, a list for `*args`), or only the method's name if it needs no arguments (`"default"`). A
model parameter takes a nested recipe. `recipe_schema(cls)` builds the pydantic core schema from the builder
methods (public methods returning `Self`), validating each one's arguments with pydantic's (experimental)
`generate_arguments_schema`, and telling steps apart by the method's name (so errors point at the bad step). New
builder methods are picked up automatically, so keep their parameters JSON-friendly (and their names: they're part
of the format). A class can't take itself as a parameter (pydantic would recurse forever).

**Serializable.** `susa.utilities.serializable.Serializable` is a pydantic type defined by its serialized form
(`serialized_schema`, validating into an instance; instances pass as they are) and `serialize()` back to it, which
pickling goes through too (`__reduce__`). A model's serialized form is its XML. An entity's is its state (an
`LVEntityState`: the connection URI and the model; `LVSnapshotState` adds its machine), whose `restore()` constructs
the entity on the current `Connection` (asserting the same URI) and `reconnect()`s it, finding the live object with
`lookup()` (none if libvirt doesn't have it). Serials and streams aren't serializable: they can't outlive their
process.

**Architecture defaults.** `arch.py` has `ARCH_DEFAULTS`, one `ArchDefaults` per libvirt arch name (machine type,
disk bus, NIC model, video, GIC, USB controller, TCG CPU, extra raw QEMU args, ...), with the hard-won quirks
commented. `MachineModel.get_defaults()` reads it for the `default*()` builders, and `disk()`/`interface()` fill in
the disk bus and NIC model from it unless they're set. For example, Malta (mips) only gives IRQs to PCI slots 11 and
12, which `next_pci_address()` enforces. KVM is used only when the guest arch is the host's and `/dev/kvm` exists;
otherwise the domain is `qemu` (TCG).

**Networking and IPs.** Interfaces get a random `52:54:00:...` MAC. `NetworkModel.interface(interface, ip=None)`
connects an interface to the network and reserves an IP for its MAC as a DHCP `<host>` entry (the first free address
in the DHCP ranges if none is given); call it before `MachineModel.interface(...)` and before the network is created.
So a machine's IP is known up front, with no waiting on DHCP leases or a guest agent: `LVMachine.interfaces` finds
each interface's IP in its network's XML, looked up in libvirt. libvirt network XML doesn't record attachments, so
`LVNetwork.interfaces` lists only the interfaces with reserved IPs. `NetworkModel.ip()` also publishes the gateway
(the host) as `host` in the network's DNS, since some guest services (e.g. rsh-redone rlogind) reverse-resolve
clients and drop them otherwise.

**Entities.** `LVEntity` (`entity.py`) keeps a model (`.model`) and the live libvirt object in `.value` (`None` when
not created); `create()` sends libvirt its `xml()` (logged at INFO). Entities use the current `Connection`
(`Connection.current_conn()`, the innermost open one), so wrap usage in `with Connection(uri):`. `Connection` also
starts libvirt's default event loop in a background thread, once per process, before the first connection opens;
without it, streams (the serial console) never receive data.

- `LVMachine` implements all the machine capabilities. It's a persistent domain: `create()` runs `defineXML` and
  starts it, and `destroy()` powers it off and undefines it, keeping the NVRAM file (a transient domain would vanish
  on `power_off()`).
- `LVSerial` opens the first console through `virDomainOpenConsole` (a `None` device name). With `qemu:///system`
  the console pty is only accessible to the `qemu` user, so it can't be opened directly. The console and
  `screenshot()` use `LVStream`, an `InputOutputStream` over a non-blocking libvirt stream (polled, since its
  readable event is level-triggered and would spin while data waits unread).
- `LVNetwork`'s `LVSniffer` runs `tcpdump` on the bridge (the host's `tcpdump` needs `cap_net_raw,cap_net_admin`).
- `LinkedClone` is a qcow2 overlay over a base image (a `Resource`: `create()` makes it, `destroy()` deletes it).

### `susa.communicator`

Transports are plain `InputOutputStream`s: `ProcessStream` is a local process in a pty (holding a `pexpect.spawn`),
used for `ssh`, `telnet` and `rlogin`, and a `Serial` is one already. `ShellCommunicator` (an `AsyncCommandRunner`)
drives a POSIX shell over the stream from its abstract `open_stream()`, writing `ENTER` (`\r`, like a terminal's Enter
key, which raw readers like rlogind's password prompt expect) and `INTERRUPT` (`\x03`) itself, and matching output
with a `PexpectStream` (clearing its `buffer` after quiet waits, which read the raw stream). It must work with
non-bash shells too (e.g. FreeBSD's `/bin/sh`), so keep shell snippets minimal and POSIX. Waiting for quiet is the
generic "the other side is done talking" signal, used in place of matching specific prompts.

- **Subclasses** just open their stream:
  - `SerialCommunicator`, over a `Serial`.
  - `SSHCommunicator`: the password comes from `SSH_ASKPASS` with `SSH_ASKPASS_REQUIRE=force`, so no prompt is
    matched. Its `write_file`/`read_file` go through `scp` over SFTP (`-s`) or legacy SCP (`-O`), or the shell
    (`"shell"`).
  - `TelnetCommunicator` and `RloginCommunicator`, over the `telnet`/`rlogin` CLI clients with `-8 -E` (on Fedora
    from the `telnet` and `rsh` packages; `rlogin` has `cap_net_bind_service` for the reserved source port rlogind
    requires).
- **Prelude:** an optional `prelude` gets the terminal before it's a shell. `login(password, username=None)` sends
  the username (if given), then the password, each once the terminal is quiet: best-effort for any getty or login
  program, and for rlogin (password only).
- **Setup:** `create()` waits for quiet, runs the prelude, and waits for quiet again, using `quiet_time` (3 s by
  default). It has to outlast whatever runs at login and silently waits on the terminal: e.g. FreeBSD's `resizewin`
  queries the terminal and waits about 1 s for a reply, swallowing input sent meanwhile (in one case the rest of the
  line started `vi`). It then sends `set +m +o emacs +o vi; stty -echo -opost -imaxbel; PS1=''; PS2=''` with the
  exit marker on the same line (turning line editing off discards whatever it already read). Line editing goes
  first: libedit (e.g. FreeBSD's `sh`) resets the terminal settings around every line it reads, and turning it off
  restores them; without readline, bash also stops emitting bracketed-paste escapes. `-imaxbel` stops the tty from
  ringing bells into the output when a burst of input fills its queue (seen over FreeBSD telnet/rlogin). After that
  there's no echo, prompt, newline translation or job notification, so output is exactly what commands wrote. If
  login discarded part of the input it retries, sending Ctrl-C first to clear the line (but not before the first
  attempt, since interrupting a shell that's still starting can kill it).
- **`execute(command) -> CompletedProcess`** is the one primitive (stdout and stderr combined): it sends the
  command, then `echo SUSA-EXIT-$?` on its own line; output is everything before that marker, and the exit code is
  taken from it. A timeout sends Ctrl-C (which also discards the pending marker line), resends the marker, and
  raises `TimeoutError`.
- **`start`** (a `ShellCommand`): `sh -c <quoted> < in > out 2> err & echo $!` in a `mktemp -d` directory, where `in`
  is a FIFO kept open by a background `sleep` until `stdin.close()` kills it; `stdin` writes are `printf` into the
  FIFO. `wait` is the shell's `wait <pid>`, whose status can only be collected once, so it's cached. `poll` is
  `kill -0`, and `kill` is `kill <pid>`. Output streams read with `tail -c +N | head -c SIZE`, and raise `EOFError`
  once the command exited and everything was read.
- **File transfer** (`posix.py`, `PosixFileTransfer`) uses POSIX commands only, over two primitives a faster channel
  may replace: `write_file` (gzipped, `printf`ed (`printf_lines`) into a `mktemp` file, then `gzip -dc`'d into place;
  there may be no decoder like `base64`, e.g. on FreeBSD 10) and `read_file` (`gzip -c`). Multiple files go as one
  tar through them (`tar -xPf`/`tar -cPf`; `-P` keeps each given path, absolute or relative).

## Tests

- `tests/libvirt/test_models.py`: snapshot tests of the generated XML (pytest-snapshot), plus model behaviour and
  recipes. Autouse fixtures fake the host arch (`x86_64`) and `Path.resolve`, so the XML doesn't depend on the host.
- `tests/libvirt/test_entities.py` runs the LV classes against libvirt's in-process mock driver (`test:///default`).
  It's fast and needs no daemon.
- `tests/utilities/test_recipe.py` tests recipes on plain classes; `tests/communicator/test_shell.py` drives a local
  shell.
- `tests/libvirt/test_machine.py` boots real machines on `qemu:///system`:
  - It holds their definitions (`ARCHITECTURES`, `DISKS`, firmware and kernel paths): the Debian images under
    `/machines`, plus FreeBSD 15.1 and 10.4 x86_64 (`freebsd`/`freebsd10`, booted with BIOS, using FreeBSD's
    `/bin/sh` to keep the shell communicator portable; see `/machines/susa-notes/freebsd.md`). It needs UEFI
    firmware for x86_64/aarch64 (`/usr/share/OVMF`, `/usr/share/AAVMF`) and the external kernels/initrds under
    `/machines/debian-*-boot`, and skips an architecture whose image is missing.
  - The images have sshd, telnet (23) and rlogin (513) servers (from inetd, see
    `/machines/susa-notes/remote-login.md`), and users `root` and `user` with password `a`. The Debian images that
    boot through GRUB have `GRUB_TIMEOUT=0`.
  - The module-scoped `setup` fixture, parametrized by architecture, boots each image once (twice, counting the power
    cycle) on a `LinkedClone` in a temp dir it makes `0o777`, so QEMU (running as another user) can read it. Each
    architecture is its own `xdist_group` (a mark on the params, with `--dist loadgroup` in `pyproject.toml`), so `-n`
    runs whole architectures in parallel. It waits up to 120 s for ping, then for the serial console to go quiet
    (boot is over), and prints the boot output.
  - The `ready` fixture snapshots the booted machine, and the function-scoped `machine` fixture reverts to it after
    every test, so tests are independent (e.g. the power cycle can run anywhere). It also patches `machine.serial()`
    so everything read from the console is attached to the test's report as a "serial" section.

## Conventions

- Keep code minimal and succinct:
  - No docstrings; abstract methods are just `...`.
  - Comments only where something really isn't clear from the code (rarely).
  - Prefer simple code over defensive code. Don't add try/except or fallbacks for cases that shouldn't happen;
    use `assert` sanity checks (e.g. `# Sanity.`) instead of silently tolerating unexpected states. Never rely on an
    `assert` for a side effect (asserts are stripped under `-O`).
  - Return early (`if not ...: return`) rather than wrapping the rest of a function in an `if`.
  - Remove API that isn't used.
- Class layout: in models, builder methods first and `get_*` getters at the end.
- Log with the `logging` module's functions directly (`logging.info(...)`), not per-module loggers.
- `# type: ignore` without error codes.
- Optional/heavy dependencies (e.g. `PIL`, `pytesseract`, `scapy`) are imported lazily inside the function that uses
  them, with `TYPE_CHECKING` imports for annotations.
- Code must run on Python 3.10:
  - Every module starts with `from __future__ import annotations` (after any docstring), since forward
    references are otherwise evaluated eagerly.
  - Generics use `TypeVar`/`Generic`, not PEP 695 (`class C[T]` or `type X = ...`).
  - Type aliases use `TypeAlias`.
  - `Self` and `override` come from `typing_extensions`.
- Mark every overriding method with `@override`, imported from `typing_extensions`. mypy's `explicit-override`
  check is enabled, so a missing one fails type-checking.
