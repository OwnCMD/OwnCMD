# Install Community

Install the readable Community distribution and create your first Owner.

Applies to: Community

## Before you start

Use a dedicated Linux host with systemd, Linux 5.6+, Python 3.12+, x86-64 or ARM64, at least 4 GB RAM (8 GB recommended), and at least 18 GB free disk for runtime builds. Installation changes system packages, Docker runtimes, services and firewall rules. Read the included installer before running it.


## Download, check and install


```text
unzip owncmd-community.zip
cd owncmd-community
bash install.sh --check-system
sudo bash install.sh
```

## Make the installation choices

1. Enter a hostname, IPv4 address, or accept localhost.
2. Choose HTTP or optional HTTPS. A domain and certificate are not required for a private HTTP installation.
3. Enter OpenRouter and Exa keys, or press Enter to skip either key.
4. Let the installer run its database, sandbox and application checks.
5. Open the displayed URL and use the private setup token to create the first Owner.
6. Add any skipped keys under Instance settings → Providers.

## If installation stops

Keep the full error output and resolve the first failing dependency or runtime check. Do not skip the gVisor or firewall gates. Rerunning the installer is the normal retry path. Do not use --fresh-install as a repair shortcut; it is destructive.


## Deployment boundary

The archive includes built frontend assets, Python source, sandbox source and test scripts. See the release validation notes before production deployment. Full native deployment and each distribution still need real-host validation; local regression tests are not a production certification.


## Prepare a dedicated host

Check the host architecture, kernel, memory and available disk before starting. The runtime images and build stages need additional working space, so avoid filling a host to its nominal minimum. Use a supported systemd Linux installation with root access and functioning outbound package downloads. Do not run the installer inside an ordinary application container.

On Ubuntu 24.04/26.04 and Debian 13, the automatic path installs the required packages. On another systemd distribution, read the Linux compatibility guide and prepare every dependency first. The --prepared-host flag skips package-manager work; it does not skip security or runtime validation. A successful prerequisite report only confirms the checks it can perform at that stage.


## Decide how you will reach the application

For a server on a trusted LAN or VPN, use its private IPv4 address and HTTP. You do not need to purchase a domain or request a certificate. For a host reached through the public internet, use HTTPS. Selecting localhost binds the site to loopback, so a browser on a different machine will need an appropriate tunnel.

Choose the origin before inviting users. The application checks the exact scheme, hostname and port on writes. Opening the same server through a different name can make sign-in or save actions fail even when the page loads. The installer currently handles standard ports, not arbitrary reverse-proxy arrangements.


## What installation changes

The installer sets up database access, service accounts, protected configuration, the application release and sandbox image. It configures Docker to use gVisor and installs firewall rules for the execution networks. Caddy serves the frontend and proxies application traffic. This is why a dedicated host is preferable to a server already running unrelated Docker or web workloads.

The release includes prebuilt frontend assets. Node is needed when changing and rebuilding the frontend source, not for a normal server installation. The source is unpacked and readable: inspect install.sh and its scripts/configure_*.py helpers before running them with sudo.


## Verify the first installation

1. Confirm the installer finishes without bypassed runtime checks and record the displayed application URL.
2. Store the setup token privately and use it to create the first Owner; do not put it into a public issue or screenshot.
3. Open Instance settings → Providers and confirm you can save or leave provider settings unconfigured.
4. Run sudo owncmdctl status and sudo owncmdctl smoke on the host. The normal smoke check does not make paid model calls.
5. Add a provider key when ready and try one small Chat task. Test web search separately after configuring Exa.
6. Back up the installation and /etc/aster/config.env off-host before inviting other users.

## Recover from an interrupted attempt

Read the first failure, not just the final service error. A missing PostgreSQL extension, unsupported Docker firewall backend or failed gVisor check must be fixed before retrying. Rerun the normal installer after addressing the cause. Keep the same installation mode unless the host preparation genuinely changed.

Never add --fresh-install simply because a retry failed. That option is a deliberate reset that removes data, local backups and keys. If a host already contains a Community instance, first collect its status and backup; if it contains the managed SaaS edition, use a separate host instead.

