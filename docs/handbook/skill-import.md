# Import, export, and version Skill packages

Move reusable instructions and resources between installations.

Applies to: Both

## Package contents

Skills can include resources within scripts/, references/, templates/, or assets/. Paths must be safe and relative; absolute paths, parent traversal, and unsafe names are rejected.


## Import and review

Use the Skills import control and inspect the resulting instructions and resources. Imports are parsed as data and do not execute code during import. Instructions or scripts can still influence a later task, so review packages before enabling them.


## Package limits

The package parser limits resources to 80 files, each at most 512 KB, with an 8 MB overall package budget. ZIP validation rejects unsafe entries. Very large assets should be supplied separately through the appropriate attachment workflow.


## Export and restore

Use Export for the current package or export a specific historical version from version history. Restore as new version keeps an auditable version progression.


## Import ZIP step by step

Open Skills and select Import ZIP. Choose the package, then inspect the imported name, description, matching guidance, instructions, and included resources. Confirm that the package matches your intended use before enabling it. The UI import action accepts ZIP rather than an arbitrary archive type.

Safe parsing during import means the package is treated as data at that moment. A later Work task may follow its instructions or use a script resource, so import validation is not a guarantee that the workflow is suitable or harmless. Inspect scripts and unfamiliar instructions with the same care you would apply to source code you plan to run.


## Resource layout and common errors

Resources must live below scripts/, references/, templates/, or assets/. Use a normal relative path such as references/checklist.md. The parser rejects unsafe path forms, including absolute paths and parent traversal, and applies file and package-size bounds. Do not use an imported package as a general large-file storage mechanism.

If import fails, inspect the reported issue before trying again. Check resource count and size, path spelling, and package metadata. YAML aliases and excessively nested metadata are rejected by the strict parser. Repackage valid content rather than weakening the validation. Large reference documents can be supplied through the task attachment workflow when appropriate.


## Export for reproducibility

Export the active package when sharing the current procedure or moving it to another installation. If reproducing a historical run, export the relevant historical version instead. Record which version was used with any important task result, because later edits can change behavior.

Restoring an earlier version creates a new version rather than rewriting history. This helps keep the progression understandable when rolling back an unsuccessful improvement. After importing elsewhere, verify that the destination has the required account capabilities, provider configuration, and runtime resources. A package carries instructions and bundled resources, not the source installation’s accounts, credentials, or website sign-ins.

