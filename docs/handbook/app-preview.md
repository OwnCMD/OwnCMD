# Preview a running app

Interact with an app running inside a Work project.

Applies to: Both

## Choose the application

Start the app in the workspace and choose its listening port. The preview identifies it as App followed by the port. Use App path to visit a route within that app.


## Interact with the preview

If the agent is working, select Pause OwnCMD before interacting. Preview input locks protect against competing manual and agent actions.


## Responsive views

Use Display Auto, Desktop, or Mobile to inspect layouts. Auto adapts the display to the available device space. Reload if the application or website chooses its layout only at page load.


## Preview is not deployment

The preview exposes the running task application through OwnCMD. It does not by itself publish a durable public production site. Keep source exports and arrange deployment separately when needed.


## Start and inspect a project

Ask the agent to run the application, or start it yourself from the terminal after pausing the agent. Select the matching port in the workspace preview controls. If the app listens on a different port from the one chosen, the preview will not become correct merely by waiting longer.

Use App path to navigate within the app, such as /settings or /reports, when those routes exist. Test a small complete interaction: submit a form, inspect its result, return to the previous page, and check whether the expected state remains. A screenshot of the initial page cannot establish that these actions work.


## Responsive testing with concrete checks

Use Desktop to inspect wide navigation and multi-column layouts, then Mobile for narrow screens. Look for clipped labels, horizontal overflow, inaccessible controls, and input fields hidden by the keyboard. Auto is useful for your current device but does not replace checking the layouts your users need.

Display changes do not inherently reload the app. If the app or website decides which version to serve only at page load, reload after changing the view. When reporting a layout problem, state the selected display mode, route, and action that reveals it. This makes the issue reproducible for the agent.


## Blank or non-interactive previews

If the panel is blank, check the application command in the terminal first. Confirm that the process did not exit with a syntax or dependency error and that you chose its port. Then verify the route. A missing application route is different from a runtime that never started.

If you can see the app but cannot interact, inspect the OwnCMD control state. Use Pause OwnCMD when the preview says the agent is working. Once you finish manual testing, resume deliberately and describe failures precisely. For a production release, export source and follow a separate deployment process; the preview URL and runtime are part of the task environment, not a hosting commitment.

