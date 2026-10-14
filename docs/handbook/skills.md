# Create and manage Skills

Save reusable workflows with instructions and supporting resources.

Applies to: Both

## What a Skill contains

A Skill has a name, description, tags, when-to-use and when-not-to-use guidance, capabilities, instructions, and optional resources. Capabilities describe Web search, Browser, Code sandbox, and Files; they do not grant permissions your account lacks.


## Create a Skill

Open Skills and use manual creation or Create with AI. Give a specific purpose and clear instructions. AI drafts use your model provider and must be reviewed before saving. Saving creates a version and indexes matching metadata.


## Improve and organize

Use Improve with AI to propose changes to a saved Skill. Enable or Disable controls whether a Skill is active; Archive and Unarchive help organize the list. These are distinct from creating a new version.


## Version history

Inspect previous versions, export one, or use Restore as new version. Restoration creates a new version instead of silently rewriting historical versions. Keep reusable instructions free of passwords and one-time codes.


## Write an effective reusable workflow

Choose Create Skill for the manual workflow. Use a narrow name and a description that distinguishes the task from nearby use cases. In When to use, describe recognizable situations. In When not to use, identify misleading matches. Put the actual procedure, required inputs, and completion checks in Instructions rather than hiding them in the title.

For example, a Skill for reviewing a CSV should state how to identify headers, handle missing values, report suspicious rows, and verify totals. A Skill for making a report should describe its sections and evidence requirements. Avoid promising tools or access the account does not have. A capability declaration describes the workflow; it is not a permission grant.


## AI-assisted creation and improvement

Create with AI can draft a Skill from your stated goal. Review the generated instructions, metadata, and resources before saving. Make the desired reuse explicit: a one-time task description often contains details that should become inputs rather than permanent instructions.

Improve with AI proposes changes to the saved version based on your requested improvement. Check that it preserves important constraints and does not introduce assumptions from a single example. These drafting and matching operations use provider calls and can record usage. The fact that a draft was produced successfully does not establish that the workflow was tested on real tasks.


## Maintain Skills over time

Enable a Skill when it is ready for matching and Disable it when you want to keep it without active use. Archive moves it out of the active set while keeping an organization path back through Unarchive. Use version history to understand changes and Restore as new version when an earlier procedure was better.

After a meaningful update, try a representative task and inspect whether the intended workflow was selected and followed. Keep resources small, relevant, and free of credentials. When a task fails, decide whether the problem belongs in the Skill instructions, the task input, or the runtime configuration; adding more prose cannot fix a missing provider key or blocked dependency source.

