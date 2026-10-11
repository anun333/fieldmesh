<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Modules as systemd services (spec v0.1 §8.3; open-questions Q11)

Each module runs as its own sandboxed service. Its only way to reach the farm's data is
the module host's unix socket, and the host answers only what the module's grant allows
([sdk/modhost.py](../../sdk/modhost.py)).

| unit | what it is |
| --- | --- |
| [fieldmesh-host.service](fieldmesh-host.service) | the host, over the farm's log file, reading back every two seconds what other processes append to it: readings, grants, revocations |
| [fieldmesh-module@.service](fieldmesh-module@.service) | one module: `fieldmesh-module@water`, `fieldmesh-module@soilwater` |
| [fieldmesh-server.service](fieldmesh-server.service) | the SensorThings data service, read-only over the farm's log, tokens required ([server/](../../server/)) |
| [fieldmesh-module@notify.service.d/](fieldmesh-module@notify.service.d/channels.conf) | the notifier's one exception: the network, for its push server, and its ntfy tokens as credentials ([modules/notify/](../../modules/notify/)) |
| [fieldmesh-module@twin.service.d/](fieldmesh-module@twin.service.d/frostwatch.conf) and [fieldmesh-module@twin.timer](fieldmesh-module@twin.timer) | the covered-crop frost watch ([modules/twin/](../../modules/twin/)): one run each evening at 17:30, in GreenLight's own environment, no network |
| [fieldmesh-module@board.service.d/](fieldmesh-module@board.service.d/serve.conf) | the farm page: its own state directory for the pages, served on this machine only ([modules/board/](../../modules/board/)) |

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

# Taking it back: within two seconds, the next call it makes is refused.
sudo python3 /opt/fieldmesh/sdk/modhost.py revoke --log /var/lib/fieldmesh/farm.jsonl <grant id>
```

## The notifier and the board

Both read every module's decisions, which an owner grants by installing them: their
manifests ask for it, and the grant record says so (§8.3). Neither is granted a reading.

```sh
sudo python3 /opt/fieldmesh/sdk/modhost.py grant --log /var/lib/fieldmesh/farm.jsonl \
    --manifest /opt/fieldmesh/modules/notify/module.json --token-out /etc/fieldmesh/modules/notify.token
sudoedit /etc/fieldmesh/modules/notify.json      # the roster: people, routes, channels
# optional, if the ntfy server asks for tokens (modules/notify/README.md):
sudoedit /etc/fieldmesh/modules/notify.ntfy-token /etc/fieldmesh/modules/notify.ntfy-ack-token
sudo cp -r deploy/systemd/fieldmesh-module@notify.service.d /etc/systemd/system/
sudo systemctl enable --now fieldmesh-module@notify

sudo python3 /opt/fieldmesh/sdk/modhost.py grant --log /var/lib/fieldmesh/farm.jsonl \
    --manifest /opt/fieldmesh/modules/board/module.json --token-out /etc/fieldmesh/modules/board.token
sudoedit /etc/fieldmesh/modules/board.json       # farm, time zone, languages, people's names
sudo cp -r deploy/systemd/fieldmesh-module@board.service.d /etc/systemd/system/
sudo systemctl enable --now fieldmesh-module@board   # http://127.0.0.1:8080/
```

The covered-crop frost watch runs once each evening rather than staying up:

```sh
sudo python3 -m venv /opt/fieldmesh/modules/twin/env
sudo /opt/fieldmesh/modules/twin/env/bin/pip install -r /opt/fieldmesh/modules/twin/requirements.txt
sudo python3 /opt/fieldmesh/sdk/modhost.py grant --log /var/lib/fieldmesh/farm.jsonl \
    --manifest /opt/fieldmesh/modules/twin/module.json \
    --property http://vocab.nerc.ac.uk/standard_name/air_temperature/ \
    --property http://vocab.nerc.ac.uk/standard_name/relative_humidity/ \
    --property http://vocab.nerc.ac.uk/standard_name/wind_speed/ \
    --property http://vocab.nerc.ac.uk/standard_name/cloud_area_fraction/ \
    --token-out /etc/fieldmesh/modules/twin.token
sudoedit /etc/fieldmesh/modules/twin.json        # {"lat": …, "lon": …, "cover": "thermic", "tunnel": "<id>"}
sudo cp -r deploy/systemd/fieldmesh-module@twin.service.d deploy/systemd/fieldmesh-module@twin.timer /etc/systemd/system/
sudo systemctl enable --now fieldmesh-module@twin.timer
```

Run as such a process on a copy of McAllister Farm's own forecast log, sandboxed without
network and capped at 512 MB, it read the night through the host and logged its decision.
That night took 5 seconds and 132 MB. `systemd-analyze` accepts the unit and its timer, and
scores the unit 0.4. The timer itself has not fired under a system manager.

The notifier is the one module given the network, so `systemd-analyze security` scores
its unit at 1.3 ("OK"), and the board, which serves on this machine only, at 1.2; a
module with no network scores 0.4. Run live under a user manager with the notifier's
settings, it read its roster and token as credentials, fell back to no ntfy token when
that file was missing, and published to a real ntfy server through the host. **Not
checked:** SMS through ModemManager from the service's own user, which polkit decides;
check it on the first gateway with a SIM.

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
* **Not checked live either:** dropping capabilities (`CapabilityBoundingSet=`). A user
  manager refuses it outright, so the live runs left it out. Check it under the system
  manager with `grep Cap /proc/<pid>/status`. Everything still untested is listed in
  [docs/UNTESTED.md](../../docs/UNTESTED.md).

WASI's capability sandbox is the stated target (Q11), adopted when the Python toolchain is
ready; the grant model does not change when the sandbox does.
