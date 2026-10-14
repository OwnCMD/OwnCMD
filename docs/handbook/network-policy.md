# Sandbox network policy

Understand restricted code networking and owner-controlled exceptions.

Applies to: Community

## Default isolation

Code and browser workloads use distinct Docker networks and gVisor runtimes. Code runs with a more restricted network path and a package proxy. Host metadata and private-address access are security boundaries, not normal browsing features.


## Configure code destinations

Owners manage global and account network rules through the code network policy interface. Rules can identify allowed public destinations using the supported domain, IP and subnet forms. The backend validates destination and policy data before applying it.


## Use exceptions carefully

An unrestricted code-network grant changes the account’s allowed egress policy; it does not remove authentication, ownership checks or every host-level boundary. Give exceptions only to trusted accounts with a concrete need.


## When requests fail

Check the effective account policy, destination resolution, requested port and provider/tool error. Do not fix a blocked request by disabling host firewall chains. Review global and per-account settings together.


## Host operations

Docker’s DOCKER-USER and OwnCMD’s dedicated chains must remain present. A firewall-manager reload can affect host rules; verify and reapply the isolation service as part of host maintenance. Test actual network isolation before exposing a new distribution deployment.


## Start with the failed destination

Identify which tool made the request and the hostname, protocol and port it actually needed. A browser failure and a code package-install failure may follow different network paths. Read the terminal or tool error before adding an exception; DNS failure, certificate rejection and an intentional policy block are not the same condition.

For a dependency download, remember that the initial site may redirect to another public hostname. Grant the smallest destination scope the task requires, then test again. Do not add a broad subnet just because one host has several addresses.


## Apply a policy change safely

1. Open Instance settings → Network as an Owner and inspect the current global rules.
2. Check any account-specific policy that changes the effective result for the affected member.
3. Add or adjust only the supported destination rule needed for the legitimate task.
4. Save and rerun a small request from the same account and environment.
5. Confirm that blocked host, metadata and private destinations remain blocked; success reaching one public site is not a complete isolation test.
6. Remove temporary exceptions when the work ends.

## Separate application rules from host firewall health

An allowed destination is still subject to the runtime and host network boundary. If every task loses connectivity after a Docker restart or firewall reload, inspect the infrastructure before editing per-account rules. Ensure the expected Docker and OwnCMD chains exist and that the firewall service has applied them.

The prepared-host installation path preserves these checks on other distributions. A native Docker nftables backend is not equivalent to an iptables command backed by nft compatibility. Treat that difference as an installation compatibility issue, not a reason to bypass the chain check.


## Do not use policy as a substitute for trust

An unrestricted grant is a significant privilege. Grant it only where the operator understands the account’s tasks and data exposure. It does not authorize access to other members’ files or remove authentication and ownership checks. Keep the app user out of the Docker group; the authenticated broker is the intended route to isolated execution.

