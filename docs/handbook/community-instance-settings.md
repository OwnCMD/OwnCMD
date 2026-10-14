# Instance settings and roles

Manage members, model access, resource limits and network policy as an Owner.

Applies to: Community

## Owner responsibilities

Open Instance settings from the owner navigation. The Community panel exposes Providers, member management, model configuration, resource policy and code network policy. These are instance controls, distinct from Cloud’s larger SaaS administration product.


## Membership controls

Owners can invite users, adjust Owner/Member roles, suspend access and revoke sessions. Keep a recovery path and more than one trusted operator when appropriate. The server prevents removal of the last active Owner.


## Model access

Configure the models exposed for Chat and Work. Global and account policy determines what a user can choose; a provider advertising a model does not itself make it available to every member. Check both the permitted model list and provider configuration when a choice is missing.


## Resource policy

Configure limits supported by the panel for accounts and workloads. Workspace storage/file limits and runtime capacity prevent unbounded use of shared resources. Application spending limits are estimates, not provider-enforced billing guarantees.


## Member boundary

Members manage their own conversations, files, memory, skills, schedules and usage. They cannot configure instance secrets or administer other users. The API enforces permissions independently of what the UI displays.


## Navigate the Owner panel

Instance settings has four tabs: Providers, Members, Models and Network. Resource limits are in Models under “Models and resource limits”; there is not a separate resource dashboard. Members see their own user settings, not these instance-wide controls.

Providers manages shared OpenRouter and Exa credentials. Members manages invitations, roles, suspension and session revocation. Models controls permitted model IDs and resource values. Network opens the code-network policy editor. Change one area at a time so you can attribute a failure to the relevant policy.


## Set the Chat and Work model lists

1. Open Models and review Chat models and Work models separately.
2. Use provider model IDs, one per line, rather than display names copied from marketing pages.
3. Place the intended Auto default first in each list; the panel uses that first entry for Auto.
4. Keep a usable model in each required mode and save with Save models and limits. The save validates models with OpenRouter, so a working provider key is needed.
5. Start a small new Chat and Work request to confirm the resulting choices. A previously selected model can become unavailable after a policy change.

## Adjust limits deliberately

The same form exposes the supported policy limits as numeric fields, with server-provided minimum and maximum values. Keep resource limits within the capacity of the host. Raising an account or task limit does not add memory, disk or execution capacity to the machine.

Usage estimates and provider-side billing are different boundaries. A daily spending value of zero means unlimited, not “no spending allowed.” Where a limit is based on estimated model cost, delayed reconciliation can change the final recorded amount. Use upstream account budgets as an additional control.


## Handle simultaneous administration

Settings updates carry a version so one Owner does not silently overwrite another Owner’s newer changes. If a save is rejected because the state changed, reload and review the current values before applying your intended edit again. Do not keep submitting the old form.

Before changing a member’s role or disabling access, confirm which account you selected. Revoke sessions when an account is compromised or access should end promptly. Verify a replacement Owner can sign in before removing an existing operator’s ownership.

