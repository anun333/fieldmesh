<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Modules as systemd services (spec v0.1 §8.3; open-questions Q11)

Each module runs as its own sandboxed service. Its only way to reach the farm's data is
the module host's unix socket, and the host answers only what the module's grant allows
([sdk/modhost.py](../../sdk/modhost.py)).

| unit | what it is |
| --- | --- |
| [fieldmesh-host.service](fieldmesh-host.service) | the host, over the farm's log, for a farm that runs it on its own (on a gateway it runs inside the gateway) |
| [fieldmesh-module@.service](fieldmesh-module@.service) | one module: `fieldmesh-module@water`, `fieldmesh-module@soilwater` |
| [fieldmesh-server.service](fieldmesh-server.service) | the SensorThings data service, read-only over the farm's log, tokens required ([server/](../../server/)) |

## Installing a module

```sh
sudo useradd --system fieldmesh && sudo groupadd --system fieldmesh-modules
sudo cp -r . /opt/fieldmesh                      # the repository, read-only to services
sudo install -d -m 0700 /etc/fieldmesh/modules

# The owner's act (§8.2): grant the module its points. Only the token's hash is logged.
sudo python3 /opt/fieldmesh/sdk/modhost.py grant --log /var/lib/fieldmesh/farm.jsonl \
    --manifest /opt/fieldmesh/modules/water/module.json \
    --datastream <trough series id> --datastream <trough series id> \
    --token-out /etc/fieldmesh/modules/water.token
sudoedit /etc/fieldmesh/modules/water.json        # {"troughs": [{"datastream": …, "capacity_l": 400}]}

sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl enable --now fieldmesh-host fieldmesh-module@water

# Taking it back: the next call it makes is refused.
sudo python3 /opt/fieldmesh/sdk/modhost.py revoke --log /var/lib/fieldmesh/farm.jsonl <grant id>
```

## What the sandbox does, and what was checked

The module service has its own throwaway user, no network (address families other than
unix sockets refused), a read-only system and no home, no way to gain privileges, a
system-call filter, and limits on memory, CPU and processes, so a runaway module cannot
starve the foundation. Its token and configuration arrive as systemd credentials, readable
by it alone and gone when it stops.

* `systemd-analyze security` scores the module unit at an exposure of **0.4, "SAFE"**, and
  `systemd-analyze verify` accepts both units.
* Run live under a *user* systemd manager, sandboxed as above, the water monitor connected
  to a real host, judged a demo trough and raised its alert by name; inside the same
  sandbox an IPv4 or IPv6 socket was **refused** and the module socket connected.
* **Not checked live:** the filesystem protections (`ProtectSystem`, `ProtectHome`). A
  user manager skips mount-namespace options without telling you — in that run the home
  directory was still writable — so they take effect only under the system manager, which
  needs root to test. Check them on a real gateway with
  `systemd-run -p ProtectSystem=strict … touch /usr/x` before relying on them.

WASI's capability sandbox is the stated target (Q11), adopted when the Python toolchain is
ready; the grant model does not change when the sandbox does.
