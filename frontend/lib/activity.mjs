export function currentTurn(events = []) {
  let boundary = -1;
  for (let i = events.length - 1; i >= 0; i--)
    if (events[i].kind === "followup") {
      boundary = i;
      break;
    }
  return events.slice(boundary + 1);
}
export function activitySteps(events = []) {
  const steps = [],
    calls = new Map(),
    seen = new Set();
  let pendingPlan = null,
    thinking = null;
  for (const event of currentTurn(events)) {
    if (event.id != null && seen.has(event.id)) continue;
    if (event.id != null) seen.add(event.id);
    if (
      [
        "chat_delta",
        "title_updated",
        "app_preview",
        "completed",
        "turn_completed",
        "chat_completed",
      ].includes(event.kind)
    ) {
      thinking = null;
      continue;
    }
    if (event.kind === "thinking") {
      thinking = { ...event, status: "running" };
      continue;
    }
    if (event.kind === "plan") {
      thinking = null;
      pendingPlan = {
        ...event,
        status: "running",
        started: null,
        finished: null,
      };
      steps.push(pendingPlan);
      continue;
    }
    if (event.kind === "tool_started") {
      thinking = null;
      const existing = event.body?.call_id && calls.get(event.body.call_id);
      const step = existing || pendingPlan || { ...event };
      const id = step.id;
      // Preserve identity across plan → running → finished and approval retries.
      if (!existing || !existing.finished)
        Object.assign(step, event, {
          id,
          status: "running",
          started: event,
          finished: null,
        });
      if (!existing && !pendingPlan) steps.push(step);
      pendingPlan = null;
      if (event.body?.call_id) calls.set(event.body.call_id, step);
    } else if (event.kind === "tool_finished") {
      thinking = null;
      const step = event.body?.call_id
        ? calls.get(event.body.call_id)
        : [...steps]
            .reverse()
            .find(
              (s) =>
                s.kind === "tool_started" &&
                !s.finished &&
                s.body?.name === event.body?.name,
            );
      if (step)
        Object.assign(step, {
          body: { ...step.body, ...event.body },
          finished: event,
          status: event.body?.ok === false ? "failed" : "completed",
        });
      else {
        const item = {
          ...event,
          status: event.body?.ok === false ? "failed" : "completed",
          finished: event,
        };
        steps.push(item);
        if (event.body?.call_id) calls.set(event.body.call_id, item);
      }
    } else {
      if (
        ["failed", "cancelled", "credit_paused", "pause", "retry"].includes(
          event.kind,
        )
      )
        thinking = null;
      steps.push({
        ...event,
        status:
          event.body?.ok === false ||
          ["failed", "cancelled"].includes(event.kind)
            ? "failed"
            : "completed",
        finished: event,
      });
    }
  }
  if (thinking) steps.push(thinking);
  return steps;
}
