# Passwords and account recovery

Change a password or recover an account without an email service.

Applies to: Community

## Change your own password

A signed-in user can change their password in Settings. Use the current-password check and choose a strong replacement. Community has no verification-code email or password-reset email endpoint.


## Recover from the server

An authorized server operator can reset the password for an existing account:


```text
sudo owncmdctl reset-password owner@example.com
```

## Session revocation

The recovery command revokes existing sessions. The user must sign in again with the replacement credentials. Protect the operator console and share any temporary password privately.


## Access management

For a departed or compromised member, an Owner can suspend the account and revoke sessions. Recover the rightful Owner through server administration if necessary; do not make public registration available as an account-recovery workaround.


## Choose the right recovery path

If you can sign in, use the password-change controls in Settings and provide your current password. If you cannot sign in, ask an authorized server operator to use the CLI. Community does not have email reset codes, email verification or a mail queue, so waiting for a reset email cannot resolve the problem.

The account identifier is the email value used during registration. Confirm the intended instance and identifier before resetting anything. A Cloud account at console.owncmd.com is separate and uses the Cloud recovery flow.


## Run the server reset interactively

Connect to the correct host through your normal administrative channel. Run owncmdctl reset-password followed by the existing account’s identifier. The command asks for a new password and confirmation without placing the password in the shell arguments. Use 12–128 characters as required by the command.

A successful reset revokes existing sessions. The account must sign in again; a browser still showing a previous page does not mean its session remains valid. Share any temporary credential privately and have the user replace it through Settings. Do not put a password in a public issue, script, shell history or chat transcript.


## Check suspension and role separately

A password reset is not the same as reactivating a disabled account. If the password is correct but access is blocked, a current Owner should inspect the account’s state. If ownership itself must be recovered, the host administrator has separate create-admin and grant-admin operations; these map to Community’s Owner role.

Do not edit password hashes directly or delete accounts to bypass recovery. That can break ownership and conversation relationships. Preserve the last active Owner invariant during routine access changes.


## After suspected compromise

1. Suspend the affected account and revoke its sessions through an authorized Owner where appropriate.
2. Reset its password from a trusted administrative session.
3. Review whether it had Owner privileges and whether provider or network settings were changed.
4. Rotate provider credentials at the upstream account if an Owner or the host may have been compromised.
5. Restore access only after the cause is understood. A password reset alone does not repair a compromised host.
