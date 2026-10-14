#!/usr/bin/env bash
# Sourced by install.sh. Keep the installer's private umask for all secrets.
# The optional root is for isolated filesystem regression tests only.
configure_gvisor_repository() (
 set -euo pipefail
 local_root=${1:-}
 key_dir="$local_root/usr/share/keyrings"
 source_dir="$local_root/etc/apt/sources.list.d"
 command -v curl >/dev/null && command -v gpg >/dev/null || {
  echo 'Repairing the gVisor repository requires curl and gnupg.' >&2; exit 1;
 }
 install -d -m 0755 "$key_dir" "$source_dir"
 stage=$(mktemp -d "$key_dir/.aster-gvisor.XXXXXX")
 source_stage=''
 trap 'rm -rf -- "$stage"; if [[ -n "$source_stage" ]]; then rm -f -- "$source_stage"; fi' EXIT
 install -d -m 0700 "$stage/gnupg"
 curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  --connect-timeout 15 --max-time 90 --retry 2 --retry-max-time 180 \
  https://gvisor.dev/archive.key -o "$stage/archive.asc"
 gpg --batch --no-options --homedir "$stage/gnupg" --dearmor --output "$stage/key.gpg" "$stage/archive.asc"
 gpg --batch --no-options --homedir "$stage/gnupg" --with-colons --show-keys "$stage/key.gpg" > "$stage/key.info"
 awk -F: '$1 == "pub" { found=1 } END { exit !found }' "$stage/key.info" || {
  echo 'The gVisor archive download did not contain a valid public signing key.' >&2; exit 1;
 }
 # Prepare both files before publishing. A failed download/conversion leaves
 # the previous repository and key untouched; .gpg contains binary OpenPGP.
 source_stage=$(mktemp "$source_dir/.aster-gvisor.XXXXXX")
 printf 'deb [arch=%s signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main\n' "$(dpkg --print-architecture)" > "$source_stage"
 chmod 0644 "$source_stage"
 install -m 0644 "$stage/key.gpg" "$stage/published.gpg"
 mv -fT "$stage/published.gpg" "$key_dir/gvisor-archive-keyring.gpg"
 mv -fT "$source_stage" "$source_dir/gvisor.list"
)

repair_existing_gvisor_repository() {
 local root=${1:-}
 gvisor_repository_prepared=0
 if [[ -e "$root/etc/apt/sources.list.d/gvisor.list" || -L "$root/etc/apt/sources.list.d/gvisor.list" ]]; then
  configure_gvisor_repository "$root"
  gvisor_repository_prepared=1
 fi
}
