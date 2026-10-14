# Chat: answers and research

Use Chat for conversation, explanations, document questions, and web research.

Applies to: Both

## Start a conversation

Choose Chat, select a model or leave Auto selected, and send your question. Responses stream into the conversation. Continue in the same thread when the previous context matters.

1. Choose Chat from the mode control.
2. Write your question and optionally attach supported images or documents.
3. Send the message and review the response and any source cards.
4. Ask follow-up questions in the same conversation.

## What Chat can do

Chat can search the public web and read supported document attachments, including inspecting PDF page images. It can explain code and provide code examples. It does not execute code, operate a browser, or create files in a project workspace.


## Write a useful request

Include the outcome, audience, constraints, and desired format. For research, state the date range and what needs verification. For document questions, identify the document and relevant page, sheet, or section.


## Long conversations

An internal conversation notebook preserves key decisions and research evidence and supports retrieval of earlier messages omitted from model context. It is not a downloadable document or a substitute for saving the final answer.


## A complete first-session example

For a comparison task, give the assistant the choices, decision criteria, and output format in one message. For example: “Compare these two proposals using implementation effort, ongoing maintenance, and assumptions. Use a table, identify unanswered questions, and do not infer prices that are missing.” This gives the conversation a clear goal without requiring browser or code execution.

After the initial answer, refine the same conversation: “Expand the maintenance comparison and show which proposal supports each claim.” Refer to earlier material by name rather than assuming the model can identify an ambiguous “that.” When changing subject entirely, start a new conversation so unrelated context does not influence the answer.


## Attachments, streaming, and interruptions

Attach a document before sending the question and wait for it to finish processing. Tell OwnCMD whether to summarize the whole document, extract specific fields, or answer a narrow question. A message such as “What does page 12 say about termination?” is easier to verify than “Analyze this.” Image attachments use a different upload path and remain available in temporary Chat.

Only one response can be generated at a time in the same conversation. If the interface says OwnCMD is still answering the previous message, wait for completion or use the available stop control before submitting another instruction. A partial streamed response is not necessarily the final answer; review the completed response and source cards before copying it elsewhere.


## Diagnose an unexpected answer

First check the selected mode: Chat cannot use a project terminal or operate a website. If you requested execution, accept a Work handoff or create a Work task. Next check whether the answer needs current evidence. Ask the assistant to search, provide supporting sources, and explicitly identify uncertainty. Finally, check that the correct attachment completed processing.

A model can misunderstand a request or misread a document. Correct the specific misunderstanding and provide the desired result instead of repeatedly sending the same vague prompt. For technical work, ask for assumptions and concrete examples. For sensitive decisions, verify the underlying evidence yourself; fluent wording is not proof that a fact is correct.

