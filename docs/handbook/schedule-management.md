# Manage runs and missed schedules

Pause automation, run a task immediately, and inspect its history.

Applies to: Both

## Schedule controls

Use Pause schedule or Resume schedule to control future execution. Run now requests an immediate run. Delete schedule removes the automation after confirmation.


## Run history

Run history links to the Work conversation and displays statuses such as Queued, Running, Completed, Failed, Paused, Needs your input, Stopped, Skipped, or Conversation deleted. Open the linked conversation to address an approval or failure.


## Missed executions

The implementation supports latest and skip missed-run policies. It coalesces recurring missed slots rather than creating a burst of catch-up runs, and avoids overlapping runs of the same schedule. The skip policy treats runs more than 15 minutes overdue as missed.


## Unattended does not mean unrestricted

A scheduled task can still require input, website authentication, or action approval. Review runs marked Needs your input. Scheduling does not bypass account capabilities or network policy.


## Review a run from the schedule list

Open Scheduled work and locate the schedule. Inspect the latest run status and expand Run history for recent executions. Follow the linked Work conversation to see the output, activity, and any input request. The history status is a summary; the conversation contains the details needed to understand a failure or approval.

Needs your input is actionable: open the run and answer or decline the request. Failed calls for inspection of the actual error. Conversation deleted means its linked thread was removed and cannot serve as the result view. These conditions should not all be treated as a scheduler timing problem.


## Pause, resume, and run immediately

Pause schedule controls future scheduling. Before resuming, review the prompt, stored inputs, timezone, and limits, especially after a long pause. Run now is useful for checking a corrected task without waiting for its next calendar slot, but it is still a real Work run and can record usage.

Do not confuse pausing the schedule with responding to an active conversation. A running or waiting Work task has its own control state. Inspect that task separately if you intend to stop current work. Repeatedly clicking Run now is not a substitute for diagnosing a previous failed run, and overlapping-run safeguards still apply.


## Missed runs and clean retirement

If the server is unavailable when work is due, the missed-run policy determines how scheduling resumes. The implementation coalesces missed recurring slots rather than launching every missed execution in a burst. With skip, a run more than 15 minutes overdue is skipped. Review upcoming timing and history after downtime rather than assuming all missed work was recreated.

When the automation is no longer needed, download useful results and use Delete schedule with its confirmation. Deleting the automation is distinct from deleting individual conversations. If you only want to suspend it temporarily, Pause schedule preserves a clearer path to resume. Before troubleshooting a missing next run, check end date, maximum runs, enabled state, and whether another run is still active or waiting.

