# First Owner and invitations

Secure first-run setup, closed registration and manual member invitation links.

Applies to: Community

## Create the first Owner

The installer generates a private OWNCMD_SETUP_TOKEN. Enter it on the first-run form with your display name, email identifier and password. Treat this token as a secret. Setup is guarded server-side and is unavailable after an active instance owner has been established.


## Invite a member

1. Sign in as an Owner and open Instance settings.
2. Create an invitation for the intended email identifier.
3. Copy the link and share it privately using your own communication channel.
4. The recipient opens the link and completes registration with the matching email.

## Invitation lifecycle

Invitations are random, single-use, email-bound links valid for 24 hours. Stored invitation tokens are hashed. Owners can revoke outstanding invitations. The issuing account must still have owner privileges for an invitation to remain usable. OwnCMD Community does not send the link by email.


## Roles and recovery

Owners manage the instance; Members use their own workspace. At least one active Owner must remain. Internal API/database role values are admin and user, displayed as Owner and Member. If an Owner forgets a password, use the server recovery command in the account-recovery guide.


## Complete bootstrap privately

The first-run token authorizes creation of the initial Owner; knowing the server URL is not sufficient. Keep the terminal output containing the token private. Use the display name, email identifier and password you intend to use on this instance. Community does not send a verification message, so type the identifier carefully.

After setup, use the normal sign-in screen. A second visitor cannot use first-run setup to claim ownership of an established instance. If the first Owner loses access, use server-side recovery instead of clearing the user table or reopening bootstrap.


## Send an invitation end to end

1. Open Instance settings → Members while signed in as an Owner.
2. Enter the intended member’s email identifier and create the invitation.
3. Copy the generated link to a private channel you control. Community does not deliver invitation email.
4. Ask the recipient to open the complete link before its 24-hour expiry. The token is carried in the URL fragment; losing that part makes the link unusable.
5. The recipient registers with the matching identifier and their own password. Confirm their account appears in Members.
6. Revoke any unneeded invitations. To replace an expired or revoked link, issue a new invitation instead of editing the old URL.

## Explain roles before granting ownership

A Member uses their own conversations, files and workflows. An Owner can change instance-wide providers, model access, limits and network policy as well as member access. Ownership is an operational privilege, not a subscription tier. Give it only to people trusted with the server’s shared configuration and provider spending.

The last active Owner cannot be removed through routine membership changes. If transferring responsibility, create and verify the replacement Owner’s access first. Disabling or demoting an invitation issuer can invalidate outstanding invitations; reissue them from a current Owner if appropriate.


## Invitation troubleshooting

If a link is rejected, check the email identifier, expiry, whether it was already redeemed or revoked, and whether its issuer remains an Owner. Do not share a successful invitation with several people; it is single-use. If registration succeeded but sign-in fails, recover that account rather than creating another invitation for the same person.

