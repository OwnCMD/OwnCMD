# Code editor and formatting

Use the integrated editor to inspect and modify project source.

Applies to: Both

## Read and edit code

Select a source file in the project explorer. The editor supports syntax-aware display, file tabs, and line wrapping. Use the wrap control when long lines extend beyond the available width.


## Formatting

Format document is available for supported file types, with Shift+Alt+F shown as its shortcut. A formatted preview is explicitly labelled Formatted preview · saved file unchanged; viewing it does not itself rewrite your saved file.


## Saving

Save your edits before switching files or closing the workspace. If a file is truncated or too large for the editing path, download it for full inspection rather than assuming the preview contains everything.


## Editing while the agent runs

The workspace displays OwnCMD is working. Pause to edit files or interact with the workspace. Use Pause OwnCMD, make your changes, and resume the task when ready.


## Use the editing controls deliberately

Select the file, inspect its path, and choose Edit file. The editor can show multiple file tabs, but unsaved modifications still need an explicit Save file or Discard decision. Save file writes the current edited content; Discard restores the version loaded into the editor and exits editing. Check the Unsaved indicator before navigating away.

A filename helps the editor determine language behavior, so use the correct extension for new files. For example, JavaScript and JSON have different syntax rules even if their contents look similar. If the application’s error points to another file, follow that path in the explorer rather than editing a similarly named file in a different directory.


## Formatting versus functional changes

Format document adjusts presentation for supported syntax. The interface distinguishes a formatted preview from saved source, so inspect the status text before assuming the project has changed. Formatting is not a repair for missing imports, incorrect business logic, or a dependency that is not installed.

If formatting reports a syntax problem, locate and fix that problem before expecting a useful formatted result. Wrap long lines is a viewing preference: it changes how text fits the editor width without inserting line breaks into the file. These distinctions matter when reviewing generated code that is long or compact but still valid.


## Verify edits and handle read-only previews

After saving, run an appropriate project check and revisit the app preview. A changed file may require the development server’s normal refresh or rebuild behavior. If the preview still shows old behavior, check that the file you edited is actually imported or served by the application.

Editing is disabled when OwnCMD has control and for truncated previews. Pause the agent for manual changes; download an oversized file for complete inspection. Do not treat read-only display as a permissions bug until you check those conditions. When returning work to the agent, describe the exact file and the change so it can continue from the current source.

