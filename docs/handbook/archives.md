# Archive attachments in Work

Bring compressed project or data files into a Work task.

Applies to: Both

## Use Work mode

Archives are accepted only in Work and require upload, Work, and code permissions. If you see Switch to Work mode to upload archives, change modes before attaching the archive.


## Supported archive extensions

The accepted list is .zip, .zipx, .7z, .rar, .tar, .gz, .tgz, .bz2, .tbz2, .xz, .txz, .zst, and .tzst. An accepted extension does not guarantee that every encryption method or unusual archive variant is readable.


## Prepare the task

Describe the important files and expected outcome. For source code, include the build or start instructions if known. For data, specify the schema or report you need.


## Resource limits

Archive upload size follows the configured file and storage limits. Runtime extraction and resulting project contents also remain subject to workspace policy. Split very large archives and exclude unnecessary dependency folders when possible.


## Prepare an archive for the task

Place the files required for the task in a coherent directory structure. For a software project, include source, package manifests, lockfiles, and any relevant start instructions. Avoid unnecessary generated dependency folders when the task can recreate them; they consume transfer and workspace capacity without clarifying the application.

For a dataset archive, explain which files should be used and whether similarly named files are alternate versions or complementary data. Include headers, units, and any schema notes. Compression preserves bytes, but it does not tell the agent which files are authoritative or what analysis is intended.


## Upload and inspect in Work

Switch to Work before selecting the archive. Wait for the upload flow to complete and ask the agent to inspect the archive contents before making changes. A useful instruction is to identify the project structure and required dependencies, then proceed with the requested outcome.

If Work or code capability is disabled for the account, the archive workflow is unavailable even if ordinary PDFs upload successfully. Ask the operator to review the relevant permission. An archive’s supported filename extension only identifies an accepted upload type; unusual compression options, corruption, or protection can still prevent useful extraction.


## Manage size and extraction problems

Compressed size is not the same as extracted workspace size. A modest download can expand into many files or large data, so account workspace limits still matter after transfer. If the task reports a quota error, reduce the archive to the required content or ask the owner to review the configured limit.

Do not solve a parser or extraction error by repeatedly renaming the extension. Recreate the archive in a supported standard form and verify that it opens locally. Provide an unprotected copy only when appropriate for the data. After the task edits a project, use Export project to preserve the full result rather than downloading a single source file and assuming it contains the rest of the archive.

