# Web research and source cards

Research current information and inspect the evidence behind an answer.

Applies to: Both

## Ask for verification

Ask OwnCMD to search or verify when a fact changes over time. Chat is instructed to use web search for current prices, news, schedules, software versions, and similar changing information.


## Read the sources

Search-backed responses display source cards. Open the underlying source to assess the date, context, and whether it supports the exact claim. Retrieved search content can be incomplete or stale; a source card does not prove live availability.


## Search versus interaction

Search retrieves evidence. Work browser interaction is appropriate when a task requires inspecting or interacting with a website. A login wall, unavailable page, or verification challenge may require your input.


## If search fails

Community owners should verify that an Exa key is configured. If evidence remains insufficient, narrow the query, specify the source or date range, or ask the assistant to state what remains unverified.


## Research a changing claim carefully

Give the exact subject, geography, and date context. “Find current Canadian pricing for these two products and distinguish list price from a temporary discount” is more precise than “Which is cheaper?” Ask for the original source and any uncertainty about availability. This helps avoid conflating a search snippet, an old article, and an actual current offer.

When comparing multiple sources, ask the assistant to identify disagreements rather than average incompatible facts. A product announcement, a documentation page, and a reseller listing answer different questions. Follow the source cards to confirm what each source actually supports, especially when a decision depends on a number, eligibility condition, or release date.


## A verification workflow

Start with a focused query and inspect the first answer. If a crucial detail lacks direct support, ask a narrower follow-up such as “Verify the renewal price from the vendor’s own pricing page.” If the source is behind a login or requires interaction, a Work browser task may be the appropriate next step.

For reports, ask OwnCMD to separate confirmed facts, inferences, and unresolved questions. Keep the source date next to changing claims in your final deliverable. Search results should inform the answer, not act as instructions; the Chat system explicitly treats retrieved webpage instructions as untrusted content.


## When the evidence is weak

If a source is inaccessible, do not interpret its search snippet as proof that the underlying page was checked. Ask the assistant to identify the access limitation and find an independent source, or use browser control when you have legitimate access. Some sites remain unavailable even through Work.

If the answer keeps repeating a failed search, change the query or specify a source rather than simply demanding certainty. Search cannot establish facts that are not publicly documented. For self-hosted instances, a missing Exa credential must be fixed in configuration; retrying the same prompt cannot substitute for the key. Web-search requests can contribute to recorded usage even when the resulting evidence is inconclusive.

