#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
fresh_install=0
dry_run=0
prepared_host=0
check_system=0
for arg in "$@"; do
 case "$arg" in
  --prepared-host) prepared_host=1 ;;
  --check-system) check_system=1 ;;
  --fresh-install) fresh_install=1 ;;
  --dry-run) dry_run=1 ;;
  --help|-h)
   echo 'Usage: sudo bash install.sh [--prepared-host] [--check-system] [--fresh-install [--dry-run]]'
   echo '--prepared-host uses installed dependencies without running a package manager.'
   echo '--check-system reports prerequisites without changing the host; sudo is not required.'
   echo '--fresh-install permanently erases the previous local OwnCMD installation, including backups and keys.'
   echo '--dry-run previews the reset without deleting anything; requires --fresh-install.'
   exit 0 ;;
  *) echo "Unknown option: $arg"; exit 2 ;;
 esac
done
if [[ $dry_run == 1 && $fresh_install == 0 ]]; then echo '--dry-run requires --fresh-install'; exit 2; fi
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Reject unsupported capabilities before taking locks, resetting data or changing packages.
[[ $(uname -s) == Linux ]] || { echo 'OwnCMD requires Linux.'; exit 1; }
command -v python3 >/dev/null || { echo 'Install Python 3.12+ as python3 first.'; exit 1; }
# os-release is parsed as data, never sourced as shell code.
package_mode=$(python3 - "$HERE" <<'HOST'
import sys
sys.path.insert(0, sys.argv[1] + '/scripts')
from linux_host import automatic_packages, os_release
print('apt' if automatic_packages(os_release()) else 'prepared')
HOST
)
if [[ $prepared_host == 1 ]]; then package_mode=prepared; fi
host_args=()
if [[ $package_mode == prepared ]]; then host_args=(--prepared-host); fi
python3 "$HERE/scripts/linux_host.py" "${host_args[@]}"
if [[ $check_system == 1 ]]; then exit 0; fi
[[ $EUID -eq 0 ]] || { echo 'Run this installer with sudo.'; exit 1; }
exec 9>/var/lock/aster-install.lock
flock -n 9 || { echo 'Another installation is running.'; exit 1; }
export OWNCMD_PACKAGE_MODE="$package_mode"
mem=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
(( mem >= 3800000 )) || { echo 'At least 4 GB RAM is required; 8 GB or more is recommended.'; exit 1; }
if [[ $fresh_install == 1 ]]; then
 reset_args=()
 if [[ $dry_run == 1 ]]; then reset_args=(--dry-run); fi
 python3 "$HERE/scripts/reset_installation.py" "${reset_args[@]}"
 if [[ $dry_run == 1 ]]; then exit 0; fi
fi
free=$(df -Pk /opt | awk 'NR==2 {print $4}')
required_disk=18000000
# Runtime refresh rebuilds package layers; reserve full build space on upgrades too.
(( free >= required_disk )) || { echo "Insufficient free space: need $((required_disk / 1000000)) GB remaining for this install/update."; echo 'Inspect docker system df and old releases before retrying.'; exit 1; }
if [[ -s /etc/caddy/Caddyfile && ! -f /etc/aster/installed && ! -f /etc/aster/install-started ]]; then
 echo 'An existing Caddy configuration was found. Refusing to overwrite it. Use a dedicated host or integrate this package manually.'; exit 1
fi
# Never silently convert a SaaS database or overwrite its services.
if [[ -f /etc/aster/config.env ]] && ! grep -qx 'OWNCMD_EDITION=community' /etc/aster/config.env; then
 echo 'Existing non-community deployment detected. Install Community on a separate host; in-place SaaS conversion is not supported.'; exit 1
fi
previous=""
if [[ -L /opt/aster/current ]]; then
 previous=$(readlink -f /opt/aster/current 2>/dev/null || true)
 [[ "$previous" == /opt/aster/releases/* && -d "$previous" ]] || previous=""
fi
# Back up existing application data before modifying services or Docker.
if [[ -n $previous && -x /usr/local/bin/asterctl && -f /etc/aster/config.env ]]; then
 echo 'Backing up existing application data before upgrade…'
 /usr/local/bin/asterctl backup
fi
activated=0
cutover_started=0
postgres_committed=0
worker_units=()
atomic_current(){
 local target=$1 tmp="/opt/aster/.current.$$.tmp"
 rm -f "$tmp"
 ln -s "$target" "$tmp"
 mv -Tf "$tmp" /opt/aster/current
}
rollback(){
 rc=$?
 echo "Installation stopped (exit $rc). Review the error above."
 if [[ $postgres_committed == 1 || ( $cutover_started == 1 && -f /etc/aster/postgresql-cutover ) ]]; then
  systemctl stop aster-api aster-broker "${worker_units[@]}" 2>/dev/null || true
  echo 'PostgreSQL data is preserved. Services stopped; refusing to roll back to a release that could write stale SQLite data. Fix the reported error and rerun this installer.'
  exit "$rc"
 fi
 if [[ $cutover_started == 1 && $activated == 0 && -n $previous ]]; then
  systemctl start aster-broker aster-api "${worker_units[@]}" 2>/dev/null || true
 fi
 if [[ $activated == 1 ]]; then
  if [[ -n $previous && -d $previous ]]; then
   atomic_current "$previous"
   systemctl restart aster-api aster-broker aster-worker@1 2>/dev/null || true
   echo 'Previous application release restored. Data and keys were preserved.'
  else
   systemctl stop aster-api aster-broker aster-worker@1 2>/dev/null || true
   rm -f /opt/aster/current
   echo 'No valid previous release existed; failed services were stopped. Data and keys were preserved.'
  fi
 fi
 exit "$rc"
}
trap rollback ERR
install -d -m 750 /etc/aster
install -m 600 /dev/null /etc/aster/install-started
if [[ $package_mode == apt ]]; then
export DEBIAN_FRONTEND=noninteractive
# A previous attempt can leave the public key root-only under umask 077.
# Repair it before the FIRST apt update, including malformed/partial keys.
source "$HERE/scripts/gvisor_repository.sh"
repair_existing_gvisor_repository
apt-get update
# Preserve installed PostgreSQL majors; default meta-package only on fresh hosts.
pg_packages=()
for pg_bin in /usr/lib/postgresql/*/bin/postgres; do
 if [[ -x "$pg_bin" ]]; then pg_major=${pg_bin#/usr/lib/postgresql/}; pg_major=${pg_major%%/*}; pg_packages+=("postgresql-$pg_major" "postgresql-client-$pg_major"); fi
done
if [[ ${#pg_packages[@]} == 0 ]]; then pg_packages=(postgresql postgresql-client); fi
apt-get install -y ca-certificates curl gnupg python3 python3-venv poppler-utils tesseract-ocr tesseract-ocr-eng docker.io caddy iptables "${pg_packages[@]}"
systemctl enable --now docker postgresql
# Refresh the signed stable gVisor package on upgrades too; an existing binary
# does not mean it is current. gVisor has no LTS release channel.
 if [[ $gvisor_repository_prepared == 0 ]]; then configure_gvisor_repository; fi
 apt-get update
 apt-get install -y runsc
runsc_bin=$(dpkg-query -L runsc | awk '/\/bin\/runsc$/ {print; exit}')
[[ -n "$runsc_bin" && -x "$runsc_bin" ]] || { echo 'The installed gVisor package has no executable runsc.'; exit 1; }
else
 # Package names/repositories are owned by the operator on other distributions.
 # The full gVisor distribution (including companion binaries) must be installed.
 runsc_bin=$(command -v runsc)
 systemctl enable --now docker
 # Versioned PostgreSQL units may expose postgresql.service as an alias.
 # Their canonical boot enablement belongs to prepared-host provisioning.
 systemctl start postgresql
fi
# Share complete PostgreSQL tool discovery with the disposable regression cluster.
pg_bindir=$(python3 "$HERE/scripts/linux_host.py" --pg-bindir)
export OWNCMD_PG_BINDIR="$pg_bindir"
export PATH="$pg_bindir:$PATH"
# In prepared mode, verify local administrative access without rewriting pg_hba.conf.
# New clusters must use peer auth on this socket and SCRAM passwords on loopback.
if [[ $package_mode == prepared ]]; then
 runuser -u postgres -- "$pg_bindir/psql" -X --no-password -h /var/run/postgresql -U postgres -d postgres -v ON_ERROR_STOP=1 -c 'SELECT 1' </dev/null
fi
"$runsc_bin" --version
printf "Host kernel: %s\n" "$(uname -r)"
"$runsc_bin" install
# Browser sandboxes use a separate gVisor runtime with network passthrough inside
# their dedicated Docker namespace. Code sandboxes retain the stricter netstack.
python3 - "$runsc_bin" <<'PY'
import json,pathlib,sys
p=pathlib.Path('/etc/docker/daemon.json')
cfg=json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
runtimes=cfg.setdefault('runtimes',{})
base=runtimes.get('runsc',{})
path=sys.argv[1]
base['path']=path
# Workspace volumes must reach the host tmpfs, never a runsc tmpfs overlay.
# Keep operator runtime flags; the final value overrides any previous overlay2.
args=base.get('runtimeArgs',[])
if not args or args[-1]!='--overlay2=root:self':args=[*args,'--overlay2=root:self']
base['runtimeArgs']=args
runtimes['runsc']=base
runtimes['runsc-browser']={'path':path,'runtimeArgs':['--network=host']}
p.write_text(json.dumps(cfg,indent=2)+'\n')
PY
dockerd --validate --config-file=/etc/docker/daemon.json
systemctl restart docker
iptables -S DOCKER-USER >/dev/null || { echo "Docker must use its iptables firewall backend (iptables-nft is supported). No sandbox firewall checks are bypassed."; exit 1; }
# Verify both actual runtimes. Never fall back to ordinary containers.
docker run --rm --runtime=runsc --network=none hello-world
docker info --format '{{json .Runtimes}}' | grep -q 'runsc-browser' || { echo 'runsc-browser runtime failed to register'; exit 1; }
id aster >/dev/null 2>&1 || useradd --system --home /var/lib/aster --create-home --shell "$(command -v nologin)" aster
install -d -m 750 -o root -g aster /etc/aster
install -d -m 700 -o aster -g aster /var/lib/aster
install -d -m 755 /opt/aster /opt/aster/releases
python3 "$HERE/scripts/configure_site.py" setup < /dev/tty
# Keep distro-specific PostgreSQL clients available to services and CLI backups.
python3 - "$pg_bindir" <<'PGPATH'
from pathlib import Path
import sys
p = Path('/etc/aster/config.env')
rows = [line for line in p.read_text().splitlines() if not line.startswith('OWNCMD_PG_BINDIR=')]
p.write_text('\n'.join(rows) + '\nOWNCMD_PG_BINDIR=' + sys.argv[1] + '\n')
PGPATH
chown root:aster /etc/aster/config.env
chmod 640 /etc/aster/config.env
# v12 fixes model routing by product mode. Preserve secrets/operator limits while migrating
# older installations away from ASTER_MODEL / ASTER_FALLBACK_MODELS.
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/aster/config.env')
rows=[]
for line in p.read_text().splitlines():
 if not line or '=' not in line: continue
 k,v=line.split('=',1)
 if k in ('ASTER_MODEL','ASTER_FALLBACK_MODELS','ASTER_CHAT_MODEL','ASTER_WORK_MODEL'): continue
 rows.append((k,v))
rows += [('ASTER_CHAT_MODEL','google/gemini-3.5-flash-lite'),('ASTER_WORK_MODEL','openai/gpt-5.6-luna')]
p.write_text(''.join(k+'='+v+'\n' for k,v in rows))
PY
chown root:aster /etc/aster/config.env
chmod 640 /etc/aster/config.env
# Defaults preserve existing operator configuration.
python3 - <<'DEFAULTS'
from pathlib import Path
p=Path('/etc/aster/config.env');text=p.read_text();values=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
for key,value in {'ASTER_CODE_MEMORY':'2048m','ASTER_CODE_CPUS':'2','ASTER_BROWSER_COST_PER_HOUR':'0','ASTER_CODE_COST_PER_HOUR':'0','ASTER_SKILL_EMBEDDING_MODEL':'google/gemini-embedding-2','ASTER_SKILL_EMBEDDING_DIMENSIONS':'1536'}.items():
 if key not in values:text+=key+'='+value+'\n'
p.write_text(text)
DEFAULTS
# Environment file contains only installer-generated single-line values. Never shell-source it.
release=/opt/aster/releases/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -m 755 "$release"
cp -a "$HERE"/. "$release"/
python3 -m venv "$release/venv"
"$release/venv/bin/pip" install --disable-pip-version-check -r "$release/requirements.lock"
python3 "$release/scripts/verify_frontend.py"
"$release/venv/bin/python" -m compileall -q "$release/app" "$release/sandbox"
cd "$release"
"$release/venv/bin/python" "$release/scripts/configure_pgvector.py" --test-tools
bash "$release/scripts/test_postgresql.sh" "$release/venv/bin/python"
# A new image tag preserves the previous major runtime for older releases.
# Fetch current patches; no host credentials enter the image context.
docker build --pull --build-arg "ASTER_RUNTIME_REFRESH=$(date -u +%s)" -t aster-sandbox:3 "$release/sandbox"
# Host-side unit tests run directly on the Linux host, but production code execution happens inside this image.
# Validate the actual gVisor code sandbox and its Python alias before activation.
docker run --rm --runtime=runsc --network=none --entrypoint python aster-sandbox:3 -c 'assert 2+2==4; print("CODE_SANDBOX_PYTHON_OK")'
if ! docker network inspect aster-sandbox >/dev/null 2>&1; then
 docker network create --subnet 172.30.0.0/16 --opt com.docker.network.bridge.enable_icc=false aster-sandbox
fi
if ! docker network inspect aster-code >/dev/null 2>&1; then
 docker network create --internal --subnet 172.31.0.0/16 --opt com.docker.network.bridge.enable_icc=false aster-code
fi
[[ $(docker network inspect aster-code --format '{{(index .IPAM.Config 0).Subnet}}') == 172.31.0.0/16 ]] || { echo 'Code subnet mismatch'; exit 1; }
[[ $(docker network inspect aster-code --format '{{.Internal}}') == true ]] || { echo 'Code network must be internal'; exit 1; }
for network in aster-code aster-sandbox; do
 [[ $(docker network inspect "$network" --format '{{index .Options "com.docker.network.bridge.enable_icc"}}') == false ]] || { echo 'Inter-container communication must be disabled'; exit 1; }
done
actual_subnet=$(docker network inspect aster-sandbox --format '{{(index .IPAM.Config 0).Subnet}}')
[[ "$actual_subnet" == 172.30.0.0/16 ]] || { echo 'Sandbox network subnet mismatch'; exit 1; }
# Apply OwnCMD's private-range policy before validating browser egress.
bash "$release/firewall.sh"
# Preserve the image PATH: login shells reset it and hide Go/Rust/PostgreSQL.
# Verify compiled runtimes and database binaries in the actual code runtime.
docker run --rm --runtime=runsc --network=none --entrypoint bash aster-sandbox:3 -c 'node --version && npm --version && gcc --version && g++ --version && go version && rustc --version && cargo --version && initdb --version && pg_ctl --version && java -version && php --version && ruby --version && sqlite3 --version && mongod --version && mongodump --version && cd /opt/templates/mern && npm test'
# Both probes use exactly the broker's Docker local-volume tmpfs construction.
# Check hard byte/file limits before the longer language/database runtime suite.
python3 "$HERE/scripts/verify_workspace_storage.py"
runtime_work_mount=$(python3 "$HERE/app/workspace_storage.py" 1536 100000)
# Compiled programs and build tools must execute from the private code mounts.
docker run --rm --runtime=runsc --network=none --memory=2048m --cpus=2 --pids-limit=512 --cap-drop=ALL --security-opt=no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,nodev,exec,size=256m,uid=1000,gid=1000 --mount "$runtime_work_mount" --entrypoint python aster-sandbox:3 /opt/verify_runtime.py

# Launch and capture with the production read-only browser mounts before activation.
docker run --rm --runtime=runsc-browser --network=none --memory=1024m --cpus=1 --pids-limit=512 --cap-drop=ALL --security-opt=no-new-privileges --read-only -e ASTER_SANDBOX_KIND=browser --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m,uid=1000,gid=1000 --tmpfs /work:rw,nosuid,nodev,noexec,size=1536m,uid=1000,gid=1000 --shm-size=128m --entrypoint python aster-sandbox:3 /opt/verify_browser.py
# Validate the exact browser runtime/network path used in production.
docker run --rm -i --runtime=runsc-browser --network=aster-sandbox --dns=1.1.1.1 --dns=8.8.8.8 --entrypoint python aster-sandbox:3 - <<'PY'
import socket,urllib.request
socket.gethostbyname('example.com')
with urllib.request.urlopen('https://example.com/',timeout=15) as r:
 assert b'Example Domain' in r.read()
for host,port in [('172.30.0.1',80),('169.254.169.254',80)]:
 s=socket.socket();s.settimeout(2)
 try:
  s.connect((host,port));raise SystemExit('Browser sandbox unexpectedly reached private address '+host)
 except OSError:pass
 finally:s.close()
print('BROWSER_NETWORK_OK')
PY
cat > /etc/systemd/system/aster-firewall.service <<UNIT
[Unit]
Description=OwnCMD isolated sandbox network policy
Requires=docker.service
After=docker.service
Before=aster-broker.service
PartOf=docker.service
[Service]
Type=oneshot
ExecStart=$release/firewall.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/aster-package-proxy.service <<UNIT
[Unit]
Description=OwnCMD restricted package registry proxy
After=docker.service aster-firewall.service
Requires=docker.service aster-firewall.service
[Service]
User=aster
Group=aster
WorkingDirectory=$release
Environment="PATH=$pg_bindir:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=/etc/aster/config.env
ExecStart=$release/venv/bin/python -m app.package_proxy
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/aster-broker.service <<UNIT
[Unit]
Description=OwnCMD restricted Docker broker
After=docker.service aster-firewall.service aster-package-proxy.service postgresql.service
Requires=docker.service aster-firewall.service aster-package-proxy.service
[Service]
WorkingDirectory=/opt/aster/current
Environment="PATH=$pg_bindir:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=/etc/aster/config.env
ExecStart=/opt/aster/current/venv/bin/uvicorn app.broker:app --host 127.0.0.1 --port 8091 --no-access-log
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectHome=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/aster-api.service <<UNIT
[Unit]
Description=OwnCMD web API
After=network-online.target aster-broker.service postgresql.service
Wants=network-online.target
[Service]
User=aster
Group=aster
WorkingDirectory=/opt/aster/current
Environment="PATH=$pg_bindir:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=/etc/aster/config.env
ExecStart=/opt/aster/current/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-access-log
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/aster
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/aster-worker@.service <<UNIT
[Unit]
Description=OwnCMD durable task worker %i
After=network-online.target aster-broker.service postgresql.service
Wants=network-online.target
[Service]
User=aster
Group=aster
WorkingDirectory=/opt/aster/current
Environment="PATH=$pg_bindir:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=/etc/aster/config.env
ExecStart=/opt/aster/current/venv/bin/python -m app.worker
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/aster
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
# New code and tests are ready; pause every application database writer for cutover.
"$release/venv/bin/python" "$release/scripts/configure_postgresql.py"
"$release/venv/bin/python" "$release/scripts/configure_pgvector.py"
mapfile -t worker_units < <(systemctl list-units --all --state=active,activating,reloading --plain --no-legend 'aster-worker@*.service' | awk '{print $1}')
if [[ ${#worker_units[@]} == 0 ]]; then worker_units=(aster-worker@1.service); fi
cutover_started=1
systemctl daemon-reload
systemctl stop aster-api aster-broker aster-package-proxy "${worker_units[@]}"
# Process termination completes before the WAL-aware snapshot/import begins.
# The durable sentinel also prevents stale-data rollback after a later retry.
postgres_committed=1
install -m 600 /dev/null /etc/aster/postgresql-cutover
"$release/venv/bin/python" "$release/scripts/with_config.py" "$release/venv/bin/python" "$release/scripts/cutover_postgresql.py"
chown -R aster:aster /var/lib/aster/backups 2>/dev/null || true
chmod -R a+rX "$release"
install -m 755 "$release/asterctl" /usr/local/bin/asterctl
ln -sf /usr/local/bin/asterctl /usr/local/bin/owncmdctl
# Replace current atomically. Preserve any stale real directory left by a broken old install.
if [[ -e /opt/aster/current && ! -L /opt/aster/current ]]; then
 mv /opt/aster/current "/opt/aster/current.stale.$(date -u +%Y%m%dT%H%M%SZ)"
fi
atomic_current "$release"
activated=1
systemctl daemon-reload
systemctl enable --now aster-firewall aster-package-proxy aster-broker aster-api aster-worker@1
systemctl restart aster-firewall aster-package-proxy aster-broker aster-api "${worker_units[@]}"
python3 "$release/scripts/configure_site.py" configure
systemctl enable --now caddy
systemctl reload caddy
python3 "$release/scripts/configure_site.py" verify
asterctl smoke
install -m 600 /dev/null /etc/aster/installed
trap - ERR
printf '\nInstallation and local smoke checks passed.\n'
asterctl status
python3 - <<'SUMMARY'
from pathlib import Path
values=dict(line.split('=',1) for line in Path('/etc/aster/config.env').read_text().splitlines() if '=' in line)
print('\nOpen '+values['ASTER_ORIGIN']+' to create your owner account.')
print('Setup token (keep private): '+values.get('OWNCMD_SETUP_TOKEN',''))
print('API keys are optional. Add or change them in Instance settings > Providers.')
print('After adding keys, run sudo owncmdctl smoke --live to test provider access.')
print('Back up /etc/aster/config.env securely; its encryption key is required to restore data.')
SUMMARY
