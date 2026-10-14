# Configure provider keys

Add, replace or remove OpenRouter and Exa keys without reinstalling.

Applies to: Community

## What each key enables

OpenRouter supplies model access. Exa supplies search/page retrieval. Keys are optional for installing the application, but a feature that depends on a provider needs its corresponding key and a usable provider account.


## Configure through the panel

1. Sign in as an Owner.
2. Open Instance settings → Providers.
3. Enter the OpenRouter key, Exa key, or both.
4. Save and check the configured status.
5. Start a small task that exercises the provider to verify the account and model permissions.

## Changing and removing keys

Keys are write-only: the panel returns configuration status, not stored plaintext. Leaving an input blank preserves the current key. Use the explicit removal control to clear it. A stored removal also masks an environment fallback, preventing an old installer key from unexpectedly becoming active.


## When a change takes effect

The API and worker read provider settings at request time. Updates do not require restarting the instance. An already-sent provider request cannot be recalled by replacing a key.


## Protect your keys

Use provider-side budgets and scoped credentials where available. Members cannot read or modify shared provider credentials. Saved values are encrypted using the instance master key. Back up that master key securely; losing it can make encrypted state unrecoverable.


## Install first, configure later

The installer accepts empty OpenRouter and Exa values. Skipping them does not prevent first-owner setup or access to instance settings. It does mean tasks that call those services cannot complete until the required credentials are available. There is no requirement to enter both keys merely to finish installing.

OpenRouter enables model-powered work; Exa enables the configured web search and page-retrieval integration. Test them independently. A saved key is not proof that the upstream account has balance, permission for a selected model or uninterrupted availability.


## Rotate a credential with minimal disruption

1. Create a replacement key in the provider account and retain control of the old key while you verify the replacement.
2. In Instance settings → Providers, paste the new value only into the intended provider field. Leave the other field blank to preserve it.
3. Save and check for a success message. Reload the settings if a concurrent-update error appears instead of repeatedly resubmitting stale state.
4. Run one small request that uses the provider and inspect the result and Usage.
5. Revoke the old key at the provider after the replacement works. If the old key is compromised, revoke it immediately and accept that in-flight requests may fail.

## Understand blank, remove and environment fallback

A blank form input means “leave unchanged,” not “erase.” Use the explicit remove action when you want a provider disabled. A saved removal also suppresses an installer environment value, so deleting a key does not unexpectedly reactivate an older one.

Stored keys are encrypted and never sent back as plaintext to the settings form. It is normal for a configured key input to look empty after saving. Use the status shown beside it. Do not paste secrets into Chat to test them or include them in screenshots of failed requests.


## Diagnose authentication and availability errors

An authentication error usually points to the actual key or upstream account. A model-access error may instead reflect an unavailable model, allowed-model policy or provider permissions. A balance error belongs to the provider account in Community; adding Cloud credits does not fund it.

For a search failure, confirm Exa separately even if Chat works. After rotation, new requests read the saved settings without an application restart. Requests already sent to a provider are not cancelled by changing a key. Use provider-side budgets and inspect Usage to understand the cost of a verification request.

