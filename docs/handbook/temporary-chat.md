# Temporary chats

Ask questions without saving the conversation to history.

Applies to: Both

## Turn temporary mode on

In Chat, use Turn on temporary chat. The conversation displays Temporary chat · not saved to history. This mode is unavailable in Work.


## What is retained

Conversation state and its notebook remain in process memory rather than the task/event database or disk. Content-free usage records remain. Temporary mode does not eliminate processing by the model or search provider.


## Session lifetime

The implementation expires temporary sessions after 30 minutes idle or eight hours absolute. Navigation, logout, or process restart discards the session. Do not use a temporary chat for material you need to recover later.


## Attachments and memory

Images are supported. Document uploads require a saved conversation, so turn temporary mode off to attach documents. Temporary Chat does not load your saved memories. Up to five temporary sessions per account are allowed by the current implementation.


## Use temporary mode intentionally

Turn temporary mode on before starting a conversation you do not want in saved history. Confirm the notice in the thread instead of assuming that closing a normal chat makes it temporary. Keep the session open while you need its context, and copy any answer you wish to retain before navigating away.

Temporary mode is appropriate for a short discussion or one-off image question. A long-running project, scheduled task, or document-analysis workflow should use a saved conversation. The mode intentionally trades recoverability for reduced application-side persistence; a restart can end it even when the eight-hour absolute limit has not been reached.


## Understand the privacy boundary

The application keeps temporary conversation state in its process memory and omits the normal task/event persistence. It still sends requests to the configured AI or search providers when those capabilities are used. The absence of OwnCMD history is not a claim that an external provider has no logs or retention.

Usage records remain without conversation content. Saved memories are not loaded into temporary Chat, but anything you type in the current session is still part of that session’s context. An image you attach can be processed by the selected model. Avoid treating the feature as an anonymous network connection or a separate account.


## Recoverable errors versus ended sessions

A capacity message can occur when the account already has five temporary sessions or when the process memory budget has been reached. Close an existing temporary session or start a saved conversation. The current implementation uses bounded process-local storage, so temporary sessions are not a shared persistent database across application processes.

If you see Temporary chat has ended, the content is no longer available through the temporary store. Start a new conversation and supply the context you still have; there is no history entry to reopen. To upload a PDF or other document, turn temporary mode off and use a saved chat. If you accept Switch to Work, review the warning that the carried-over context becomes part of a saved Work conversation.

