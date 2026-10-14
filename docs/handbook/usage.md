# Understand usage

Read activity and costs correctly in Cloud and Community.

Applies to: Both

## Open Usage

Use Usage from the application navigation to inspect recorded activity. Select a date range and available mode/model filters, review the totals and breakdown, and use the row list for detail. Export CSV when you need a separate review or reconciliation.


## Cloud: charges against a wallet

Cloud usage can include model, search and browser/code runtime charges. A credit hold can reserve estimated spend before final settlement. Posted charges, pending estimates and available credit are different values. See the Cloud credit and pricing guides before interpreting a balance change.


## Community: usage without credits

Community records requests, model IDs, tokens, provider costs and runtime seconds. It has no credit balance or payment checkout. Provider usage is recorded without the SaaS multiplier. Model services such as title generation can contribute to usage even when they are not the main visible reply.


## Estimates and reconciliation

Providers may report costs later or finalize estimates after the request. Records may move from estimated to reconciled values. Your external provider invoice remains authoritative. A task limit based on estimates cannot guarantee that a provider will never bill more.


## Local runtime costs

Community browser/code runtime cost defaults to zero while runtime seconds remain recorded. Operators may configure infrastructure allocation rates through ASTER_BROWSER_COST_PER_HOUR and ASTER_CODE_COST_PER_HOUR. These are local estimates; OwnCMD Community does not collect payment.


## Unexpected activity

Check background services such as title generation, scheduled runs and provider retries. For Cloud, review pending entries and the credit ledger. For Community, compare the task time, provider record and selected model before treating a difference as a duplicate charge.


## Review one task before an aggregate total

Start with a narrow date range around a known task. Confirm whether you are viewing Chat, Work or background activity, and inspect the selected model. Large totals are easier to understand after reconciling one representative task. Export CSV when you want to compare records outside the application.

A visible reply may involve more than one operation. Title generation, search, retries and scheduled work can create usage outside the main response text. A code or browser environment can also accrue runtime seconds. Do not assume one conversation message always corresponds to one provider request.


## Distinguish the three cost questions

First, what activity occurred: requests, tokens, model IDs and runtime. Second, what the upstream provider reported or estimated for that activity. Third, for Cloud only, what the service charged against credits. These values answer different questions and can settle at different times.

Community has no wallet to fund or top up. Any configured local runtime rate is an allocation estimate for your own infrastructure. It does not send money to OwnCMD. If a provider rejects requests for insufficient funds, resolve the balance on that provider account.


## Investigate a discrepancy

1. Match the time range and timezone used for the comparison.
2. Identify the mode, model and task associated with the record.
3. Check whether the entry is estimated or has been reconciled with upstream cost.
4. Include background requests and scheduled runs, not only the visible reply.
5. For Cloud, compare finalized usage with the credit ledger and distinguish holds from posted charges.
6. For Community, compare with the external provider invoice, which remains authoritative for provider billing.

## Budgets and retained evidence

Use small verification tasks when configuring a new model or key. Model choices and long-running tasks can affect cost significantly; an application estimate is not a guarantee of a final upstream invoice. Provider budgets are a separate protective control.

When reporting an apparent error, retain timestamps, model IDs and the relevant sanitized record details. Do not include the provider API key or an entire private conversation. Cloud users can submit the evidence through Help & support. Community operators investigate their own provider and instance records.

