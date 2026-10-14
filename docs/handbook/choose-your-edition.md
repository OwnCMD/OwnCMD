# Cloud or Community?

Compare hosting, credentials, accounts, payments and operational responsibility.

Applies to: Both

## OwnCMD Cloud

Use the hosted application without provisioning the OwnCMD server stack. Sign up, verify your email, and begin with $10 in credit. Cloud includes the credit/payment experience and its own support and knowledge-base features when enabled.


## OwnCMD Community

Download the readable source and installer, provision a dedicated Linux server, and create the first Owner account with the private setup token. Invite members manually. API keys are optional during installation and can be added later in Instance settings.


## What changes between editions

- Cloud: email verification and password-recovery email. Community: email is a login identifier; no SMTP verification or recovery messages.
- Cloud: credit wallet, hosted credit purchases and usage accounting. Community: usage accounting without a wallet, top-ups or markup.
- Cloud: SaaS administrative controls, support tickets and knowledge-base management. Community: a smaller owner panel for providers, members, models, resource limits and network policy.
- Both: core conversations, model selection, browser/code workspaces, documents, skills and scheduling, subject to configuration.

## Who operates what

For Community, you manage the host OS, upgrades, keys, database, certificates if used, backups, restore tests and capacity. Cloud removes that server installation work from the user. A self-hosted deployment still sends content to configured external AI/search providers when using those features.


## Choose Cloud when you want the shortest setup

Go to console.owncmd.com, create an account and complete email verification. You receive $10 in free credits when the verified account is created; you do not pay $10 to unlock the application. Tasks consume that balance. The Cloud credit guides explain reservations, final charges, purchases and usage detail.

Cloud is a good fit when operating PostgreSQL, Docker, gVisor and a Linux host is not part of the work you want to do. You still choose what to upload, which actions to authorize and how to review results. Cloud support is available through the signed-in application.


## Choose Community when infrastructure control matters

Community is distributed under Apache License 2.0. There is no software license charge or built-in credit wallet. You choose your server and provider accounts and are responsible for those bills. Installing without keys is supported; it gives you time to set up the instance and accounts before enabling provider-dependent features.

Self-hosting does not turn remote models into local models. OpenRouter and Exa receive the requests needed to provide configured features. Review the provider relationship before using sensitive data. Community does not include provided support; the documentation, source and public contributions are the self-service path.


## Accounts do not transfer automatically

A Cloud account belongs to the hosted service. A Community account belongs to that particular instance. The same email identifier can be used in both places without linking their conversations, credits, provider configuration or sign-in sessions. Cloud credits do not become a balance on your Community server.

The Community installer deliberately rejects a SaaS configuration. Start on a separate host if you are moving away from Cloud or testing the open-source edition. This release does not supply a tested in-place Cloud-to-Community conversion. Keep your existing service available while evaluating the separate deployment.

