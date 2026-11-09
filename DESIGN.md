# SUSA design notes

## Open questions and tradeoffs

- **Recipe format verbosity.** Classes are named in full (`susa.libvirt.machine_model.LVMachineModel`) and nested models
  repeat their class (`{"model": {"…LVNetworkModel": [...]}}`). Explicit and unambiguous, but noisy. Short names
  (`"LVMachineModel"`) from the registry would read better, at the cost of a name clash policy.
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
- **virsh.** Libvirt is used through `virsh`, so nothing stays connected and there are no bindings to build. The console
  is a `virsh console` on `script`'s terminal, so its stream includes the client's banner and its escape character (`^]`) disconnects.
- **Serialization by pickle.** Entities pickle their model and look their libvirt object up again when unpickled. Simple
  and needs no schema, but only works between Python processes using the same libvirt URI.
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

## KubeVirt's rough edges

What goes beyond KubeVirt's plain API, how it works, and what it costs.

- **Keys go through the launcher's libvirt.** `KVMachine.press` runs `kubectl exec` into the `compute` container of the
  virt-launcher pod, and `virsh send-key 1 --codeset linux` there. KubeVirt's only key API is VNC, which takes X11
  keysyms. It depends on KubeVirt's internals: the container's name, the virtqemud socket's path, virsh being in the
  image, and the domain's ID being 1. The alternative is `virtctl vnc --proxy-only` with `vncdotool`: it pulls in Twisted
  and cryptography, and needs a table from each `Key` to a keysym and a proxy process.
- **A pod in the node's network.** `KVNodePod` is a `hostNetwork` pod with `NET_ADMIN` and `NET_RAW`, running a public
  image (netshoot), because bridges and capturing on them are only available on the node. It's made per operation and
  force-deleted. It needs permission to make such pods, and isn't pinned to a node, so this only works with one node.
- **The network owns its bridge.** CNI makes a bridge for the first attachment and never removes it, and a sniffer started
  before any machine would have nothing to capture. So `KVNetwork.create` adds and raises the bridge with a node pod,
  which CNI then adopts, and `destroy` deletes it. kubernetes-nmstate is the declarative way, at the cost of an operator.
  A killed process leaves its bridge behind, holding the network's address and the route to its subnet, so `create` refuses
  an address that's already on the node; delete such a bridge with `ip link del`.
- **Sniffing is `kubectl exec ... tcpdump`.** Capture bytes come through kubectl's output. Killing the client leaves
  tcpdump running until the pod is deleted, which follows immediately.
- **A NetworkAttachmentDefinition per machine with an IP.** Static IPAM lives in the definition, so each machine with an
  IP gets one (`<machine>-net<index>`) on the shared bridge. KubeVirt's bridge binding then hands the address to the
  guest over DHCP, so the guest must run DHCP on that interface. `gateway` with `isGateway` is what puts the node's
  address on the bridge. VMI status doesn't report these addresses, so `interfaces` takes them from the model.
- **`KVNetwork.interfaces` is worked out.** Kubernetes doesn't record what's attached to a definition, so it finds the
  definitions of the bridge, and the VMIs using them, with each's MAC and static IP.
- **`reboot` is `virtctl restart`.** A graceful stop and a new VMI in a new pod, rather than a reboot within the VMI, since
  `soft-reboot` failed through the guest agent. So `interfaces` is empty for a moment, and consoles end.
- **Snapshots are of disks.** KubeVirt saves no memory and only restores stopped machines, so `revert`, and `destroy` which
  reverts like `LVSnapshot`'s, stop and boot the machine. Connections to it end.
- **The firewall.** With `br_netfilter`, bridged IP goes through firewalld, which rejects it. Trusting `susa+` once
  covers default-named networks only.
- **Hooks rewrite domains.** A sidecar `onDefineDomain` hook, from a ConfigMap `KVMachine` makes, rewrites the domain's XML
  with `sed`, so it depends on the exact XML KubeVirt generates, and may break with new versions. Without KVM on Arm64,
  KubeVirt only allows a CPU mode libvirt refuses, so `aarch64_without_kvm_script` sets CPU `max` and GIC 3.
- **Other architectures.** KubeVirt's alpha `CrossArchitectureVirtualization` gate only does x86_64 and Arm64 and s390x,
  and its released images don't have the QEMU for them, so `scripts/kubevirt-launcher` adds Fedora's QEMU (apart under
  `/opt/qemu`, as its libraries are newer, behind wrappers in `/usr/bin`). x86_64 uses the gate
  (`cross_architecture`), with a hook because it asks for a CPU libvirt doesn't know. The others have no KubeVirt support:
  `emulate` makes KubeVirt generate an Arm64 domain and rewrites it for the target (`EMULATIONS`). KubeVirt doesn't know
  about it: its status, memory overhead and defaults are for Arm64. It's the least supported part of this package.
