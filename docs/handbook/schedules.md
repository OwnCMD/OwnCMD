# Create scheduled work

Run Work tasks once or on a recurring schedule.

Applies to: Both

## The setup wizard

Scheduled work uses Work, Timing, Readiness, and Review steps. Each run creates its own Work conversation with results, files, and activity.

1. Describe the task and name the schedule.
2. Choose recurrence, start time, and time zone.
3. Review required inputs and any saved prefilled values.
4. Review the upcoming times and consent settings, then save.

## Timing options

Recurrence supports Once, an hourly interval, Daily, Weekly, or Monthly. Intervals must be between 1 and 8,760 hours. Time zones use IANA identifiers. For a month without the requested day, the implementation uses the last available day.


## Limits and readiness

Optional controls include a per-run cost limit, maximum run count, and end date. The current per-run cost range is $0.01–$10,000, and run count accepts 1–10,000. These are scheduling controls, not a guarantee of an exact external provider bill.


## Review stored inputs

Scheduled inputs and consent are reviewed during creation. Changing the prompt clears consent in the editor. Disabling Personal details prefill later does not retroactively remove already approved schedule inputs.


## Example: a weekday research brief

Describe the brief’s topic, sources, required date range, and output format in Work. Then choose Weekly, select the relevant weekdays, and set the local start time and IANA time zone. Use a named zone such as America/Toronto when you want calendar behavior tied to that location rather than a fixed UTC hour.

Review the upcoming run times in the Review step before saving. A calendar schedule follows the chosen time zone. The UI states that a missing daylight-saving time is skipped and a repeated time runs once. An interval schedule instead expresses an elapsed hourly interval, so choose the recurrence that matches your intention.


## Readiness and reusable inputs

The Readiness step checks for inputs the task needs and can prefill them from Personal details. Review each value, including whether it is appropriate for repeated use. Saving an automation with outdated contact information can repeat the same error each run. Changing the prompt resets consent in the editor so that the revised task is reviewed again.

If a task requires an unpredictable login challenge or a fresh one-time code, it may still need your attention at runtime. Do not put a one-time value into reusable instructions and expect it to remain valid. An unattended research task and an authenticated website transaction have different readiness requirements.


## Bound the automation before enabling it

Use End date, maximum run count, and per-run cost controls when they help define the intended lifetime. Expand Run controls to inspect the relevant options. A cost limit constrains task behavior but does not turn external provider accounting into an exact prepaid quote; inspect actual usage after early runs.

For a new automation, review its first result before leaving it running for an extended period. Confirm that the output meets the prompt, the timezone is correct, and no repeated input is blocking it. Save a draft or keep it paused until the required configuration is available. Optional API-key setup during Community installation does not mean a scheduled AI task can run without provider credentials.

