# Terminal and runtime troubleshooting

Run commands inside the task workspace and inspect application output.

Applies to: Both

## Use the terminal

Open the terminal in Project workspace after pausing the agent when manual interaction is locked. Commands run in the task runtime, not on your own computer.


## Dependencies and network access

Package installation and outgoing requests depend on the code-network policy configured for the account and instance. A blocked domain is not resolved by changing your browser settings. Ask your instance owner to review the policy.


## Diagnose a failed app

Read the command output for the first actual error. Check installed dependencies, the working directory, and whether the application process is still running. Confirm the preview port matches the application port.


## Runtime lifecycle

Stopping the workspace ends runtime activity while preserving saved project files. Do not assume an in-memory process survives a runtime stop.


## Terminal controls explained

Open terminal starts the interactive terminal session. The toolbar shows connection state, or Input paused while OwnCMD works when manual input is locked. Reconnect requests another connection when available. End session closes the terminal session. These controls are different from stopping the entire project workspace.

Clear display clears the terminal screen; it is not a command to delete project files or stop a process. If you need to interrupt a running program, use the program’s normal terminal controls. Read the output before clearing it so you do not lose the visible error information needed for diagnosis.


## A safe diagnostic sequence

Start by checking the current directory and listing project files. Read the project’s own instructions or package scripts before running a start command. If a command fails, inspect its exit message and the first underlying error rather than repeatedly rerunning it. A dependency error, a port conflict, and an invalid source file need different fixes.

The terminal belongs to the Linux task workspace. Commands are not being executed on the phone or laptop used to view OwnCMD. Files on your device are unavailable unless uploaded. Likewise, installing a package in the task does not install it on your personal machine or automatically change the OwnCMD server environment.


```text
pwd
ls
```

## Connection and network failures

If input is disabled, pause the agent before opening or reconnecting the terminal. If the session reports a disconnected state, use Reconnect and inspect whether the runtime is still available. Do not assume that reconnecting restarts an application that has already exited; verify the process through its output and preview.

An outgoing request can be blocked by the code-network policy even when your own device can reach the same site. Report the destination and exact error to the instance owner. Do not work around the policy by switching to an undocumented endpoint. Workspace storage limits can also cause package installation failures, so distinguish permission, network, and disk-space errors.

