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
- All pre-commit hooks (what CI runs): `uv run pre-commit run --all-files`. The mypy hook is a local hook that
  runs `uv run mypy` in the project environment. The ruff hook is pinned to a different ruff version than the
  dev dependency, so the two can disagree.
- Fast tests: `uv run pytest tests/core tests/communicator tests/libvirt/test_models.py tests/libvirt/test_entities.py tests/utilities`
- Single test: `uv run pytest "tests/libvirt/test_models.py::test_machine_model_default[mips]"`
- Update XML snapshots after an intended model change: `uv run pytest tests/libvirt/test_models.py --snapshot-update`
  (the run reports each rewritten snapshot as an error; re-run without the flag and review the diff under
  `tests/libvirt/snapshots/`)
- Real-VM tests: `uv run pytest tests/libvirt/test_machine.py -n 3`. Each architecture boots once (twice,
  counting the power cycle). They need a reachable `qemu:///system`, and skip an architecture whose image is
  missing. Each architecture is its own `xdist_group` (a mark on the `base_machine` fixture's params, with
  `--dist loadgroup` in `pyproject.toml`), so `-n` runs whole architectures in parallel. Keep `-n` at about
  3: each guest has 2 GB, and many TCG guests at once starve the 6-core host and cause timeouts. Because
  of that addopt, don't pass `-p no:xdist` (pytest would reject `--dist`).

## Architecture

Two layers:

- **`susa.core`** holds backend-independent abstract classes: `Resource` (create/destroy, usable as a
  context manager), `Machine`, `Network`, and `Interface` (`mac`, and `ip` when it's known in advance).
  `Machine` and `Network` both expose an `interfaces` property. `Sniffable` networks have `sniffer()`, which
  returns a (not yet created) `Sniffer` (a `Resource` whose output is a pcap stream, with `next_packet`/`packets`
  parsing it into scapy packets, scapy imported lazily); `LVNetwork` runs `tcpdump` on
  its bridge (the host's `tcpdump` needs `cap_net_raw,cap_net_admin`). Optional machine capabilities are separate
  mixins in `core/machine.py`:
  - `Snapshottable` (`snapshot()` returns a `Snapshot`; destroying a snapshot reverts the machine)
  - `Powerable` (`is_powered_on`; `power_on`/`power_off`/`reset` are immediate; `shutdown`/`reboot` ask
    the guest)
  - `Screenshottable` (a `Screenshot` of bytes plus an optional MIME type)
  - `SerialAccessible` (`serial()` returns an already created `Serial`, which is a `Resource` and an
    `InputOutputStream`)
  - `KeyPressable` (in `core/keyboard.py`, with the `Key` enum, whose values are Linux input event codes):
    `press(keys, hold_time)` holds `Key`s together, and `type_text(text)` types letters, digits, ASCII
    symbols, space, `\n`, `\r`, `\t`, `\b` and ESC as on a US keyboard
  - `core/stream.py` has `OutputStream` (`read(size, timeout)`, which raises `EOFError` once the stream
    ended and nothing's left; `read_until`; `read_all` until EOF; `is_quiet`; and `wait_until_quiet`, which
    never starts a quiet period that can't fit before its timeout), `SavedOutputStream` (keeps what's read),
    `PexpectStream` (pexpect's `SpawnBase` over an `OutputStream`: `expect`, `before`, `match`; `read` goes
    straight to the wrapped stream, so data `expect` read past its match stays in its `buffer`), `InputStream` (`write` and `close`),
    `InputOutputStream`, and `BasicInputOutputStream` (an `OutputStream` plus an `InputStream`)
  - `KeyPressableInputStream` (an `InputStream` over a `KeyPressable` that types what's written). An
    `OutputStream` of OCR'd screen text was tried and removed: OCR output jitters between screenshots of the
    same screen, so new text can't be told apart from old without heuristics.
  - `core/interface.py` has `BasicInterface`, a plain `(mac, ip)` value (`LVInterface` is one)
- **`susa.libvirt`** implements them as `LVMachine` (all of the machine mixins), `LVNetwork`, `LVSnapshot`,
  `LVSerial` and `LVInterface`.

### Models → XML → libvirt

`susa/libvirt/*_model.py` (`machine_model.py` holds both `MachineModel`, a libvirt domain, and
`SnapshotModel`) wrap the Pydantic-XML schemas from the `pydantic-libvirt` package (a git dependency,
imported as `lvdomain` / `lvnetwork` / `lvdomainsnapshot`). Each `Model` holds an `xml_model`. It has
chainable builder methods that return `Self` (`MachineModel("x").arch("x86_64").default().memory(...)`), `build()`
to XML, `parse(xml)` back, and `get_*()` getters. Getters use the `get_` prefix because the plain names are
taken by the builder setters, e.g. `arch()` vs `get_arch()`.

The LV entities (`LVEntity` in `entity.py`) take and keep a model (`.model`). They build and log its XML at
INFO in `create()`, and hold the live libvirt object in `.value` (`None` when not created). Entities get
their libvirt connection from the process-wide "current" `Connection` (`Connection.current_conn()`), so wrap
usage in `with Connection(uri):`. `Connection` also starts libvirt's default event loop in a background
thread (`Connection._start_event_loop`), once per process, before the first connection opens. Without it, streams (the serial console)
never receive data.

`LVMachine` is a persistent domain: `create()` runs `defineXML` and then starts it, and `destroy()` powers it
off and undefines it, keeping the NVRAM file. A transient domain would vanish on `power_off()`. `LVSerial`
opens the first console through `virDomainOpenConsole` (a `None` device name). Both the console and
`screenshot()` use `LVStream`, an `InputOutputStream` over a non-blocking libvirt stream. With `qemu:///system`
the console pty is only accessible to the `qemu` user, so it can't be opened directly.

### Communicators

`susa.core.communicator` (everything is `bytes`):
- **`FileTransferrer`**: abstract `upload_single(local, remote)`/`download_single(remote, local)`, and
  `upload({local: remote})`/`download({remote: local})`, which loop over them by default.
- **`CommandRunner`** (a `FileTransferrer`): `run(command) -> subprocess.CompletedProcess[bytes]`, and `check`,
  which returns stdout and raises `CalledProcessError` on failure. Its file transfer is built on commands
  alone: data is gzipped and written with POSIX `printf` (`printf_lines`) into a `mktemp` file, then
  `gzip -dc`'d into place, and multiple files go as one gzipped tar (`tar -xzPf -`, `tar -czPf -`; `-P` keeps
  each given path, absolute or relative). Downloads are `gzip -c`/`tar -czPf -` output.
- **`AsyncCommandRunner`**: adds `start(command) -> AsyncCommand`, with `stdin` (an `InputStream`),
  `stdout` and `stderr` (`OutputStream`s), `poll`, `wait` (returns the exit code) and `kill`. Its default `run`
  is `start`, `stdin.close()`, `wait`, then `read_all` of both streams (a timeout doesn't kill the command).

`susa.communicator`: transports are plain `InputOutputStream`s. `ProcessStream` is a local process in a pty
(holding a `pexpect.spawn`), used for `ssh`, `telnet` and `rlogin`, and a `Serial` is one already.
`ShellCommunicator` (an `AsyncCommandRunner`) drives a POSIX shell over the stream from its abstract
`open_stream()`, writing `ENTER` (`\r`, like a terminal's Enter key, which raw readers like rlogind's password
prompt expect) and `INTERRUPT` (`\x03`) itself, and matching output with a `PexpectStream` over it (clearing its `buffer` after quiet waits, which read the
raw stream). The
subclasses just open theirs:
  - `SerialCommunicator`, over a `Serial`
  - `SSHCommunicator`: the password comes from `SSH_ASKPASS` with `SSH_ASKPASS_REQUIRE=force`, so no prompt is
    matched, and files go through `scp` over SFTP (`-s`) or legacy SCP (`-O`), or the shell (`"shell"`)
  - `TelnetCommunicator` and `RloginCommunicator`, over the `telnet`/`rlogin` CLI clients with `-8 -E`
    (on Fedora from the `telnet` and `rsh` packages; `rlogin` has `cap_net_bind_service` for the reserved
    source port rlogind requires)
It must work with non-bash shells too (e.g. FreeBSD's `/bin/sh`), so keep shell snippets minimal and POSIX.
Waiting for quiet is the generic "the other side is done talking" signal, used in place of matching specific
prompts.
- **Prelude:** an optional `prelude` gets the terminal before it's a shell. `login(password, username=None)`
  sends the username (if given), then the password, each once the terminal is quiet. That's
  best-effort for any getty or login program, and for rlogin (password only).
- **Setup:** `create()` waits for quiet, runs the prelude, and waits for quiet again, using `quiet_time`
  (3 s by default). It has to outlast whatever runs at login and silently waits on the terminal. For
  example, FreeBSD's `resizewin` queries the terminal and waits about 1 s for a reply. Input sent during
  that wait is swallowed, and in one case the rest of the line started `vi`. It then sets
  `set +m +o emacs +o vi; stty -echo -opost -imaxbel; PS1=''; PS2=''`, with the exit marker on the same line (turning
  line editing off discards whatever it already read). `-imaxbel` stops the tty from ringing bells into the
  output when a burst of input fills its queue (seen over FreeBSD telnet/rlogin; the data still arrives). Line editing has to go first: libedit (e.g.
  FreeBSD's `sh`) resets the terminal settings around every line it reads, and turning it off restores
  them. Without readline, bash also stops emitting bracketed-paste escapes. After that there's no echo,
  prompt, newline translation or job notification, and output is exactly what commands wrote. A retry is needed if
  login discarded part of the input; it sends Ctrl-C first to clear the line. The first attempt sends no
  Ctrl-C, since interrupting a shell that's still starting can kill it.
- **`execute(command) -> CompletedProcess`:** the one primitive (stdout and stderr combined). It sends the command, then `echo SUSA-EXIT-$?` on its own line.
  Output is everything before that marker, and the exit code is taken from it. A timeout sends Ctrl-C (which
  also discards the pending marker line), resends the marker, and raises `TimeoutError`.
- **`start`** (returns a `ShellCommand`): `sh -c <quoted> < in > out 2> err & echo $!` in a `mktemp -d`
  directory, where `in` is a FIFO kept open by a background `sleep` until `stdin.close()` kills it. `stdin`
  writes are `printf` into the FIFO. `wait` is the shell's `wait <pid>`, whose status can only be collected
  once, so it's cached. `poll` is `kill -0`, and `kill` is `kill <pid>`. Output streams read with
  `tail -c +N | head -c SIZE`, and raise `EOFError` once the command exited and everything was read.

`NetworkModel.ip()` also publishes the gateway (the host) as `host` in the network's DNS, since some guest
services (e.g. rsh-redone rlogind) reverse-resolve clients and drop them otherwise.

### Per-architecture defaults

`susa/libvirt/arch.py` has `ARCH_DEFAULTS`: one `ArchDefaults` per libvirt arch name (machine type, disk bus,
NIC model, video, GIC, USB controller, TCG CPU, extra raw QEMU args, …). The `MachineModel.default*()` and
`InterfaceModel.default(arch)` methods read it. For example, Malta (mips) only gives IRQs to PCI slots 11
and 12, which `MachineModel.next_pci_address()` enforces. KVM
is used only when the guest arch equals the host arch and `/dev/kvm` exists; otherwise the domain is
`qemu` (TCG).

### Networking and IPs

Interfaces get a random `52:54:00:…` MAC when created. `NetworkModel.interface(interface, ip=None)` connects
an interface to the network and reserves an IP for its MAC as a DHCP `<host>` entry (the first free
address in the DHCP ranges if none is given). Call it before `MachineModel.interface(...)` and before
the network is created. This makes a machine's IP known up front, with no waiting on DHCP leases or a
guest agent. `LVMachine.interfaces` looks each interface's network up in libvirt at runtime and finds its
IP in that network's (parsed) XML. `LVInterface` is just a `(mac, ip)` value. Since libvirt network XML doesn't record attachments, `LVNetwork.interfaces` lists only the interfaces
with reserved IPs.

### Tests

- `tests/libvirt/test_models.py` contains snapshot tests of the generated XML (pytest-snapshot), plus tests
  for model behaviour. Autouse fixtures there fake the host arch (`x86_64`) and `Path.resolve`, so the XML
  doesn't depend on the machine running the tests.
- `tests/libvirt/test_entities.py` runs the LV classes against libvirt's in-process mock driver
  (`test:///default`). It's fast and needs no daemon.
- `tests/libvirt/test_machine.py` holds the machine definitions (`ARCHITECTURES`, `DISKS`, firmware and
  kernel paths): the Debian images, plus FreeBSD 15.1 and 10.4 x86_64 (`freebsd`/`freebsd10`, booted with
  BIOS). The FreeBSD images use FreeBSD's `/bin/sh` rather than bash, to keep the shell communicator
  portable. See `/machines/susa-notes/freebsd.md` for how they were built. A module-scoped `base_machine` fixture, parametrized by architecture, boots each image
  from `/machines` on `qemu:///system` once. It waits up to 120 s for ping and then for the serial console to
  go quiet (boot is over). The `ready` fixture then snapshots it, and the function-scoped `machine` fixture reverts to that
  snapshot after every test, so tests are independent (e.g. the power cycle can run anywhere). It also
  patches `machine.serial()` so everything read from the console is saved (`SavedOutputStream`) and attached to
  the test's report as a "serial" section; `base_machine` prints the boot output. `test_sniff`
  captures ICMP to the machine with `network.sniffer()`. The Debian images that boot through GRUB have `GRUB_TIMEOUT=0`. All images run telnet (23) and rlogin
  (513) servers from inetd (see `/machines/susa-notes/remote-login.md`). The images have sshd enabled and users `root` and `user`, both with password
  `a`. It needs UEFI firmware for x86_64/aarch64 (`/usr/share/OVMF`, `/usr/share/AAVMF`), and the external
  kernels/initrds under `/machines/debian-*-boot`. Disk clones go through `LinkedClone` in a `0o777` temp
  dir (`susa.tmp_dir_path()`), so the QEMU process, running as another user, can read them.

## Conventions

- Keep code minimal and succinct:
  - No docstrings; abstract methods are just `...`.
  - Comments only where something really isn't clear from the code (rarely).
  - Prefer simple code over defensive code. Don't add try/except or fallbacks for cases that shouldn't happen;
    use `assert` sanity checks (e.g. `# Sanity.`) instead of silently tolerating unexpected states.
  - Remove API that isn't used.
- Class layout: in models, builder methods first and `get_*` getters at the end.
- Log with the `logging` module's functions directly (`logging.info(...)`), not per-module loggers.
- `# type: ignore` without error codes.
- General helpers go in `susa.utilities` (e.g. `susa.utilities.generic`).
- Optional/heavy dependencies (e.g. `PIL`, `pytesseract`) are imported lazily inside the function that uses
  them, with `TYPE_CHECKING` imports for annotations.
- Code must run on Python 3.10:
  - Every module starts with `from __future__ import annotations` (after any docstring), since forward
    references are otherwise evaluated eagerly.
  - Generics use `TypeVar`/`Generic`, not PEP 695 (`class C[T]` or `type X = ...`).
  - Type aliases use `TypeAlias`.
  - `Self` and `override` come from `typing_extensions`.
- Mark every overriding method with `@override`, imported from `typing_extensions`. mypy's `explicit-override`
  check is enabled, so a missing one fails type-checking.
