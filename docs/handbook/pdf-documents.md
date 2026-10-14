# PDFs, scans, and document processing

Understand how documents are parsed and what to do when processing fails.

Applies to: Both

## Text and pages

The parser extracts text into page-based chunks so the assistant can retrieve relevant portions instead of inserting every byte into a model request. Ask targeted questions and refer to page numbers where possible.


## PDF images and OCR

Chat can inspect PDF page images. Pages with little extracted text may receive OCR processing, but OCR is bounded: the parser attempts at most 40 such pages and has a time budget. A large scanned PDF is not guaranteed to be fully transcribed.


## Processing boundaries

The parser rejects documents exceeding 32 MB of extracted text or 2,000 pages. Split oversized documents into logical sections. These are extraction limits, distinct from the upload-size policy.


## Damaged or protected documents

Parsing can fail for damaged or password-protected files. Provide an accessible unprotected copy when appropriate, or export the relevant pages or text. Check table structure and extracted numbers against the original when accuracy matters.


## Ask questions that can be checked

For a PDF, identify the page or named section when possible and ask for the evidence supporting the answer. For example: “From the termination section, extract the notice period and explain whether it applies to both parties.” Check the returned statement against the original page rather than relying solely on a summary.

For spreadsheets or slide decks, identify the relevant sheet, table, or slide in your prompt. Extracted text does not necessarily preserve all visual relationships, formulas, or layout. A visually complex page may need image inspection in addition to its text, especially for charts, scanned forms, and multi-column content.


## Scanned documents and OCR limitations

Text-rich PDFs and scanned PDFs behave differently. The parser first extracts PDF text, then may attempt OCR on low-text pages within its bounded budget. A document can therefore process while some scanned pages remain less accessible than others. Do not assume that a successful upload means every visual element was transcribed.

For an image-heavy or long scanned document, split the relevant pages into a smaller file and ask a targeted question. If a number or name is ambiguous, compare it visually to the original. OCR can confuse characters even when it produces plausible text; financial amounts, identifiers, and dates deserve explicit checking.


## Resolve common parser failures

A password-protected file may need an accessible export before it can be parsed. A damaged document may need to be opened and re-exported from its originating application. If the error mentions 2,000 pages or 32 MB of extracted text, split the content; reducing the original compressed file size does not necessarily reduce extracted text.

For a spreadsheet with a very large dataset, supply the relevant rows or a CSV extract when that matches the task. For unsupported embedded objects, provide a separate supported attachment. Preserve enough context to interpret the extract correctly, including headers and units. A smaller focused input can improve verifiability, but it should not silently omit information necessary to answer the question.

