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

Instance settings has five tabs: Providers, Members, Models, Access & limits and Network. Members see their own user settings, not these instance-wide controls.

Providers manages shared OpenRouter and Exa credentials. Members manages invitations, roles, suspension and session revocation. Models controls the model catalog and Auto defaults. Access & limits controls feature availability and resource budgets. Network opens the code-network policy editor. Change one area at a time so you can attribute a failure to the relevant policy.


## Set the Chat and Work model lists

1. Open Models and review Chat models and Work models separately.
2. Search the catalog by name or model ID, then select the allowed models with checkboxes. Each model shows its provider input/output rates per million tokens, without markup.
3. Choose the Auto default explicitly from the dropdown for each mode. At least one model must remain selected.
4. Save with Save changes. The save validates models with OpenRouter, so a working provider key is needed. If the catalog cannot load, check Providers and use Retry catalog.
5. Start a small new Chat and Work request to confirm the resulting choices. A previously selected model can become unavailable after a policy change.

## Adjust limits deliberately

The Access & limits tab exposes feature switches and supported policy limits as numeric fields, with server-provided minimum and maximum values. Keep resource limits within the capacity of the host. Raising an account or task limit does not add memory, disk or execution capacity to the machine.

Usage estimates and provider-side billing are different boundaries. A daily spending value of zero means unlimited, not “no spending allowed.” Where a limit is based on estimated model cost, delayed reconciliation can change the final recorded amount. Use upstream account budgets as an additional control.


## Handle simultaneous administration

Settings updates carry a version so one Owner does not silently overwrite another Owner’s newer changes. If a save is rejected because the state changed, reload and review the current values before applying your intended edit again. Do not keep submitting the old form.

Before changing a member’s role or disabling access, confirm which account you selected. Revoke sessions when an account is compromised or access should end promptly. Verify a replacement Owner can sign in before removing an existing operator’s ownership.


## Invite and manage a member

1. Open Members and choose Invite member. Enter the intended login email and select Member or Owner. Owner grants instance-wide administration, including provider keys and other accounts.
2. Create the invitation link. Copy it and deliver it privately. OwnCMD does not send email. The link expires after 24 hours and can be redeemed once.
3. The recipient opens the link, enters their display name and a password, and creates their account. Their email is a login identifier; there is no email-verification step.
4. Search members by email, or narrow the list by role and account status. Use pagination for larger instances.
5. Choose Manage beside the exact account. Account shows the identity, current role, status, active sessions and conversation count. Role changes, suspension and session revocation require a confirmation.
6. Use the member's Models and Access & limits tabs for account-specific overrides. Use the default control beside a field to remove its override, then Save member policy. Inheritance uses the saved instance policy, never an unsaved draft. Network opens that member's network policy.

Suspending blocks access and stops active work while retaining account data. Restore access reactivates an account. Sign out sessions requires a fresh sign-in on all devices; doing this to your own account ends your current session too. The last active Owner cannot be suspended or demoted. Role and suspension changes do not implicitly save draft model edits.

## Provider connections

Provider credentials are optional during installation. Add or replace them later in Providers without reinstalling. Each provider has its own status and password field. Leaving a field empty preserves the current key. Save provider keys applies changes; keys are encrypted and never returned to this form. Removing a key is a separate confirmed action and disables that integration, including any environment fallback.

OpenRouter enables model requests; Exa enables web search. Existing features that do not need the missing integration remain usable. Shared keys are available only to the server, not to members or their browsers.
