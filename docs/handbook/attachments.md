# Upload documents and source files

Attach supported files for questions, analysis, and Work tasks.

Applies to: Both

## Supported document formats

Supported office formats are PDF, DOCX, XLSX, and PPTX. Text and data include TXT, Markdown, CSV, TSV, JSON, XML, LOG, YAML, TOML, INI, and CFG. Supported code extensions include Python, JavaScript, TypeScript, JSX, TSX, HTML, CSS, SQL, Go, Rust, Java, C/C++, shell, R, notebooks, TeX, Swift, Kotlin, Ruby, PHP, SCSS, Svelte, Vue, C#, and Dart. Legacy binary DOC/XLS/PPT formats are not listed.


## Upload a document

Attach the file to a saved Chat or Work conversation. Wait for upload and processing to finish before asking the assistant to use it. Tell the assistant which part of the document matters and what result you want.


## Resumable transfer

Documents upload in chunks. Retry can resume completed parts instead of restarting the whole transfer. A processing timeout message asks you to retry to check status; it does not necessarily mean the original upload was lost.


## Limits

Per-file and total storage limits are controlled by account policy. The default file-size policy in this source is 100 MB and can be configured within 1–512 MB. The document store also caps an account at 2,000 uploads. Temporary chats support images but not document uploads.


## A document-question workflow

Open a saved conversation and choose the attachment control. Select a supported file, watch its upload status, and wait for processing to finish. Then ask a specific question such as “Extract the renewal date and notice period from the attached agreement, quoting the relevant section names.” This lets you check the answer against the source.

For several attachments, refer to each by its filename and describe the relationship: compare them, combine their data, or use one as a template. Do not assume that a generic “use this” identifies the intended file when several are present. Keep the original documents available for verifying extracted values.


## Upload state and retries

The client uploads documents in parts and queries received parts before sending missing data. Retry can therefore continue an interrupted upload instead of duplicating completed chunks. A connection-timeout message is different from a parser failure; the former may be solved by retrying when the connection stabilizes.

After transfer, the document is processed separately. Processing is taking longer than expected asks you to retry to check its status. A failed document provides an error from processing. Read that error before converting or re-uploading, because a damaged file, unsupported extension, and storage-limit error require different actions.


## Prepare files for reliable analysis

Use a supported format with meaningful filenames. Export legacy office formats to DOCX, XLSX, or PPTX if needed; renaming an extension does not convert the file. For text and code, provide actual readable text rather than an image of source when possible. Split exceptionally large documents around logical sections so the requested evidence is easier to locate.

The account’s file and storage policies can differ from defaults, and a file that uploads successfully can still exceed extraction limits. Remove unneeded attachments when the storage quota is reached. Archives require Work with code capability; images use their own attachment rules. These are distinct workflows and should not be diagnosed as one generic upload limit.

