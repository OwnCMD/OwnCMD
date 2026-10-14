# Skill matching and selection

Understand automatic matching and explicit version selection.

Applies to: Both

## Automatic matching

Automatic matching uses indexed Skill metadata and embedding similarity, followed by a model decision on the candidates. It can choose no additional Skill. A high similarity score is not a guarantee that a Skill will run.


## Selector modes

Where the Skills selector is exposed, Auto uses matching, Selected pins explicit versions, and None disables additional Skills. Selected supports up to three enabled, unarchived Skills.


## Pinned versions

A selected Skill records a version. If a newer active version exists, the selector offers Upgrade to v followed by the version. This makes changes explicit rather than unexpectedly changing pinned instructions.


## Matching failures

The source continues without additional Skills when its final selection service is unavailable and records a selection-unavailable event. Review the task activity and provider configuration rather than assuming a failed matcher used the embedding winner.


## Help the matcher distinguish nearby Skills

Matching uses the Skill’s name, description, tags, and when-to-use guidance, so make these fields specific. Two Skills with nearly identical generic descriptions are harder to distinguish. Describe the intended input and output, and include situations where a seemingly related Skill should not apply.

Use matching checks in Skills to try representative requests when available. Test both a request that should match and one that should not. A reusable procedure should not attach itself to every conversation merely because its description contains broad words such as research, write, or analyze.


## Automatic choice versus explicit selection

Auto finds candidates and asks the selection model to decide whether they are relevant. It can choose none, and that is a valid outcome when no Skill fits. Selected is appropriate where the selector is exposed and you intentionally want specific enabled Skills; it pins their versions instead of relying on a new automatic match.

The selector supports at most three selected Skills and offers an explicit upgrade when a pinned version is older than the active version. Review the changed instructions before upgrading a schedule or repeatable task. None is useful when you want the task to proceed without additional Skill instructions rather than accidentally applying a broad workflow.


## Troubleshoot unexpected selection

Check whether the Skill is enabled, unarchived, and owned by the relevant account. Review its matching metadata and whether the task actually describes the conditions it expects. If a provider error affects embedding or final selection, inspect configuration and activity rather than treating it as a bad description alone.

The implementation does not silently substitute the embedding winner when its final decision is unavailable. It can continue without additional Skills and record that fact. A selected Skill also remains subject to the user’s request and system rules; it cannot make disabled tools available. If a Skill is selected but the task still fails, inspect the execution error separately from the matching decision.

