# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SUSA (SUSA Unified Systems API) is a Python library for programmatically working with machines. It's in very
early development and currently centered around libvirt/QEMU virtual machines on Linux, across many guest
architectures (x86_64, aarch64, mips, ppc64le, armv7l, riscv64, i686), mostly emulated with TCG.

## Commands

This project uses `uv` (Python 3.14, see `.python-version`).

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
  missing. Each architecture is its own `xdist_group` (a mark on the `machine` fixture's params, with
  `--dist loadgroup` in `pyproject.toml`), so `-n` runs whole architectures in parallel. Keep `-n` at about
  3: each guest has 2 GB, and many TCG guests at once starve the 6-core host and cause timeouts. Because
  of that addopt, don't pass `-p no:xdist` (pytest would reject `--dist`).

## Architecture

Two layers:

- **`susa.core`** holds backend-independent abstract classes: `Resource` (create/destroy, usable as a
  context manager), `Machine`, `Network`, and `Interface` (`mac`, and `ip` when it's known in advance).
  `Machine` and `Network` both expose an `interfaces` property. Optional machine capabilities are separate
  mixins in `core/machine.py`:
  - `Snapshottable` (`snapshot()` returns a `Snapshot`; destroying a snapshot reverts the machine)
  - `Powerable` (`is_powered_on`; `power_on`/`power_off`/`reset` are immediate; `shutdown`/`reboot` ask
    the guest)
  - `Screenshottable` (a `Screenshot` of bytes plus an optional MIME type)
  - `SerialAccessible` (`serial()` returns an already created `Serial` resource, whose `output` is a
    `Stream` (from `core/stream.py`: `read(size, timeout)` and `read_until`), plus `write`)
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
thread, once per process, before the first connection opens. Without it, streams (the serial console)
never receive data.

`LVMachine` is a persistent domain: `create()` runs `defineXML` and then starts it, and `destroy()` powers it
off and undefines it, keeping the NVRAM file. A transient domain would vanish on `power_off()`. `LVSerial`
opens the first console through `virDomainOpenConsole` (a `None` device name). With `qemu:///system`
the console pty is only accessible to the `qemu` user, so it can't be opened directly.

### Communicators

`susa.core.communicator` defines three classes. Everything is `bytes`:
- **`CommandRunner`**: `run(command) -> CommandResult(stdout, stderr, exit_code)`, and `check`, which
  returns stdout and raises on failure.
- **`AsyncCommandRunner`**: adds `start(command) -> Process`, whose `stdout` and `stderr` are `Stream`s,
  plus `poll`, `wait` (returns the exit code) and `kill`. Its default `run` is `start`, then `wait`, then
  read both streams.
- **`FileTransferrer`**: a separate `upload`/`download` mixin.

In `susa.communicator`, `ShellCommunicator` (an `AsyncCommandRunner` and a `FileTransferrer`) drives a POSIX
shell with pexpect in bytes mode over any `Child`: `pexpect.spawn` for `SSHCommunicator`, and a `SpawnBase`
adapter over a `core.Serial` for `SerialCommunicator`. It must work with non-bash shells too (e.g. FreeBSD's
`/bin/sh`), so keep shell snippets minimal and POSIX.
- **Quiet:** `Child.is_quiet(duration)` (from the `QuietSpawn` mixin; `Spawn` is `pexpect.spawn` plus it)
  reports whether nothing arrives for that long, discarding whatever does. `wait_until_quiet` is the generic
  "the other side is done talking" signal, used in place of matching specific prompts.
- **Prelude:** an optional `prelude` gets the connection before it's a shell. `login(username, password)`
  sends an empty line, the username and the password, each once the connection is quiet. That's best-effort
  for any getty or login program. SSH still expects OpenSSH's `assword:` prompt, since OpenSSH discards
  typed-ahead input.
- **Setup:** `create()` waits for quiet, runs the prelude, and waits for quiet again, using `quiet_time`
  (3 s by default). It has to outlast whatever runs at login and silently waits on the terminal. For
  example, FreeBSD's `resizewin` queries the terminal and waits about 1 s for a reply. Input sent during
  that wait is swallowed, and in one case the rest of the line started `vi`. It then sets
  `set +m +o emacs +o vi; stty -echo -opost; PS1=''; PS2=''`. Line editing has to go first: libedit (e.g.
  FreeBSD's `sh`) resets the terminal settings around every line it reads, and turning it off restores
  them. Without readline, bash also stops emitting bracketed-paste escapes. After that there's no echo,
  prompt, newline translation or job notification, and output is exactly what commands wrote. A retry is needed if
  login discarded part of the input; it sends Ctrl-C first to clear the line. The first attempt sends no
  Ctrl-C, since interrupting a shell that's still starting can kill it.
- **`execute(command)`:** the one primitive. It sends the command, then `echo SUSA-EXIT-$?` on its own line.
  Output is everything before that marker, and the exit code is taken from it. A timeout sends Ctrl-C (which
  also discards the pending marker line), resends the marker, and raises `TimeoutError`.
- **`start`:** `sh -c <quoted> > out 2> err < /dev/null & echo $!`, in a `mktemp -d` directory. `wait` is
  the shell's `wait <pid>`, whose status can only be collected once, so it's cached. `poll` is `kill -0`, and
  `kill` is `kill <pid>`. Streams read with `tail -c +N | head -c SIZE`.
- **Transfer:** `upload` is POSIX `printf` with octal escapes, in lines chained with `&&` and short enough
  for the terminal. No decoder is needed (FreeBSD 10 has no `base64`), and no Ctrl-D, which would end the
  shell. `download` is `cat`.

### Per-architecture defaults

`susa/libvirt/arch.py` has `ARCH_DEFAULTS`: one `ArchDefaults` per libvirt arch name (machine type, disk bus,
NIC model, video, GIC, USB controller, TCG CPU, extra raw QEMU args, …). The `MachineModel.default*()` and
`InterfaceModel.default(arch)` methods read it. Hard-won quirks live there with comments. For example,
Malta (mips) only gives IRQs to PCI slots 11 and 12, which `MachineModel.next_pci_address()` enforces. KVM
is used only when the guest arch equals the host arch and `/dev/kvm` exists; otherwise the domain is
`qemu` (TCG).

### Networking and IPs

Interfaces get a random `52:54:00:…` MAC when created. `NetworkModel.interface(interface, ip=None)` connects
an interface to the network and reserves an IP for its MAC as a DHCP `<host>` entry (the first free
address in the DHCP ranges if none is given). Call it before `MachineModel.interface(...)` and before
the network is created. This makes a machine's IP known up front, with no waiting on DHCP leases or a
guest agent. Everything is read from the stored models, not from libvirt. `LVMachine(model, networks=[...])`
takes the `LVNetwork`s its interfaces connect to, and `LVMachine.interfaces` looks each interface's IP up in
that network's `NetworkModel`. It's `None` if the network wasn't passed. `LVInterface` is just a `(mac, ip)`
value. Since libvirt network XML doesn't record attachments, `LVNetwork.interfaces` lists only the interfaces
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
  portable. See `/machines/susa-notes/freebsd.md` for how they were built. A module-scoped `machine` fixture, parametrized by architecture, boots each real
  Debian image from `/machines` on `qemu:///system` once and waits up to 120 s for ping. The ping,
  screenshot, serial-login, communicator (`uname -m`, exit codes, file transfer over serial and SSH) and
  power-cycle tests then share it. The power-cycle test must stay last,
  since it reboots the machine. The images have sshd enabled and users `root` and `user`, both with password
  `a`. It needs UEFI firmware for x86_64/aarch64 (`/usr/share/OVMF`, `/usr/share/AAVMF`), and the external
  kernels/initrds under `/machines/debian-*-boot`. Disk clones go through `LinkedClone` in a `0o777` temp
  dir (`susa.tmp_dir_path()`), so the QEMU process, running as another user, can read them.

## Conventions

- Mark every overriding method with `@override`, imported from `typing_extensions`. mypy's `explicit-override`
  check is enabled, so a missing one fails type-checking.
