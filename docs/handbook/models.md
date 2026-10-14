# Models and Auto selection

Choose from the models enabled for your account and mode.

Applies to: Both

## Choose a model

Open the model picker and search the names or provider model IDs. Chat and Work may offer different choices. Owners or cloud administrators control availability, so an unavailable model may be a policy setting rather than an application error.


## What Auto means

Auto selects the configured default for the current mode. The picker shows Default followed by that model name when it is available. Auto is not a promise to independently select the best or cheapest model for every request.


## Provider fallback

The request permits OpenRouter to fall back between providers serving the same model. OwnCMD does not submit a cross-model fallback list. A provider failure can therefore still surface as an error rather than switching to a different model.


## Costs and credentials

Provider calls consume usage. Community owners configure credentials in Instance settings; cloud users use the managed service configuration. Model availability, context capacity, and provider pricing can change.


## A step-by-step selection workflow

Open the model chooser before sending the next request. Search by the visible name or model ID, then select one of the available entries. Auto remains a useful choice when you want the instance default. Its description identifies the configured default when available, which helps you understand what will actually receive the request.

The menu is scoped to the current mode and your account. If a model appears in Chat but not Work, first check the mode-specific catalog rather than assuming a rendering bug. Community owners can review model settings; managed users should ask the service operator when an expected choice is missing. Naming a model in the prompt does not override the picker or account policy.


## Compare models with a repeatable task

To evaluate models, keep the prompt, attachments, and expected output consistent. Compare whether each response satisfies the acceptance criteria, uses evidence appropriately, and follows the required format. Use Usage to inspect recorded consumption rather than assuming that a shorter-looking answer must have cost less.

Some tasks depend heavily on tool behavior, not just prose quality. For Work, check whether the model completes the actual file or browser workflow and responds correctly to tool errors. For document questions, compare the answer to the source. Do not choose solely from the marketing name or assume all enabled models have identical vision, context, latency, or tool capabilities.


## Common configuration symptoms

No available choices can indicate a disabled model catalog or account restriction. A missing provider key is a configuration issue even when the model picker itself loads. A provider error after submission can indicate provider availability or request limits. Record the exact error and selected model when reporting a problem.

Same-model provider fallback does not promise uninterrupted service. If all routes for the selected model fail, retry later or deliberately choose another enabled model. A newly selected model does not recover work that was never saved, and changing the model does not enlarge upload limits or grant additional browser and code permissions.

