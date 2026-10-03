# SUSA design notes

## Open questions and tradeoffs

- **Recipe format verbosity.** Classes are named in full (`susa.libvirt.machine_model.MachineModel`) and nested models
  repeat their class (`{"model": {"…NetworkModel": [...]}}`). Explicit and unambiguous, but noisy. Short names
  (`"MachineModel"`) from the registry would read better, at the cost of a name clash policy.
- **One nesting form.** Nested recipes are always `{"<class>": ...}`, which works for any parameter type. Bare steps
  for model parameters (`"model": ["default"]`) were shorter but only worked for exact builder-class annotations.
- **Session order.** A session makes each recipe when it's created, so references see live objects (e.g.
  `machine.ip`). Models that refer to each other (the network reserving the machine's IP) must therefore come first, as
  their own entries, before the entities made of them.
- **Recipes vs. code.** Builder methods and constructor parameters *are* the format, so renaming one breaks recipes.
  No versioning exists yet.
- **IPs known up front.** Networks reserve each interface's IP in their DHCP hosts before boot (no waiting on leases or
  a guest agent). It needs IPv4 DHCP on one `<ip>` per network, and a subnet picked before the network exists, hence
  the per-subnet byte locks in one shared lock file.
- **Shell over any stream.** One POSIX-shell communicator over serial, ssh, telnet and rlogin. Connecting waits for
  quiet periods (and logs in) instead of matching prompts, and retries until the machine is up, so it needs no
  separate boot wait; commands then just wait for an `echo SUSA-EXIT-$?` marker. Portable (FreeBSD `sh`, old
  systems), but connecting takes seconds of quiet, and it's sensitive to programs that write late.
- **Async commands over a shell.** `start` runs commands in the background with FIFOs and polls files with `tail`, so
  streaming output costs a round trip per read. Fine for tests, poor for chatty output.
- **One console user.** A serial console has one user at a time (libvirt refuses a second). Recording the console
  while a communicator uses it would need sharing again.
- **Polling streams.** The console polls a non-blocking libvirt stream; callbacks would avoid the sleeps but need
  locking and buffering.
- **Serialization by pickle.** Entities pickle their model and the connection's URI, and look their libvirt object up
  again when unpickled. Simple and needs no schema, but only works between Python processes on the same libvirt URI.
- **Arch knowledge as a table.** `ARCH_DEFAULTS` holds only what libvirt doesn't infer (machine type, video, disk bus,
  NIC, Malta's PCI slots, QEMU arguments). Everything else is left to libvirt's defaults.
- **Disposable disks.** Machines write to qcow2 overlay volumes. `commit()` writes the changes into the base image
  (libvirt has no offline commit, so it downloads the overlay and runs `qemu-img commit`; other overlays of that image
  see the change, which is the caller's responsibility), and `commit(model)` makes a standalone copy instead.

## Features you may want

- **Short class names in recipes**, and a `susa` CLI (`susa up recipe.json`, `susa run recipe.json -- uname -a`).
- **Guest-agent communicator** (`qemu-guest-agent`, via libvirt's `qemuAgentCommand`): commands and files without
  a shell, network or login.
- **Console recording** to a file (or a log stream) for debugging boots, e.g. via QEMU's `<log file=…>` on the serial
  device, so it needs no sharing.
- **Cloud-init / image customisation** (NoCloud seed ISO) so new images don't need manual setup.
- **Port forwarding / NAT helpers** for reaching guests from other hosts.
- **Waiting helpers** on communicators (`wait_for_file`, `wait_for_port`) and a generic `wait_until` on predicates.
- **Parallel machines** in a session (create independent parts concurrently) to cut boot time.
- **Packet assertions** on `Sniffer` (filters with BPF, `tcpdump -w` to a file).
- **Other backends** behind `susa.core` (e.g. QEMU directly, containers, physical hosts over SSH only).
