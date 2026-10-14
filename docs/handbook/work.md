# Work: browser, code, and deliverables

Run multi-step tasks with a browser, code sandbox, and file workspace.

Applies to: Both

## When to choose Work

Choose Work when the result requires website interaction, executing code, developing a project, or producing downloadable files. The available tools also depend on your account permissions and instance configuration.


## Describe the finished result

Give a concrete deliverable, required inputs, and acceptance criteria. For example, ask for a spreadsheet containing specified columns, or a working app with defined interactions. The agent may ask for missing details before proceeding.


## Follow progress

The conversation displays activity and results. Review requests for input and action approval when they appear. You can pause the agent before manually interacting with its browser or development workspace.


## Finish and verify

Open generated files, inspect previews, and download anything you need to retain. A completed task does not automatically imply an externally published website or production deployment.


## Example: build and check a small application

A useful Work prompt describes behavior, files, and verification: “Build a small expense tracker with add, edit, and delete actions. Keep data locally in the app, make the layout usable on mobile, run the available checks, and provide a project download.” Add any required framework or compatibility constraint before execution begins.

Watch the activity while OwnCMD works. When the app is ready, open its preview and try the important actions rather than judging only its appearance. Open the project workspace to inspect source files or terminal output. If the result needs correction, describe the observed behavior and the expected behavior in the same Work conversation so the existing workspace remains relevant.


## Provide access without assuming access

A task that needs a private website may require you to sign in using browser control. OwnCMD does not automatically inherit sessions from the browser on your own device. A task that needs a local file requires that file to be uploaded; describing its filename does not grant access to your computer.

Before starting, supply the reference documents or archive and identify the intended output. Avoid putting passwords in reusable instructions or saved memories. When the agent requests a field or browser takeover, use that specific workflow and review what will be submitted. If an account capability is disabled, changing the prompt cannot grant it.


## Recover from a blocked or incomplete run

Read the latest activity and any input card before assuming the agent has stalled. Needs your input can mean the task is waiting for a decision rather than using compute. A failed provider request, blocked network destination, missing dependency, or unavailable website requires a different remedy, so capture the actual error text.

If manual inspection is needed, pause the agent, open the browser or workspace, and investigate. Return control when you are ready for execution to continue. Preserve useful output with file downloads or Export project before deleting the conversation. If a result is incomplete, ask for the missing piece and an explicit verification step rather than restarting all work unnecessarily.

