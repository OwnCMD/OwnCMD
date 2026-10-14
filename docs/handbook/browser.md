# Use the interactive browser

See the browser the agent uses and take control when needed.

Applies to: Both

## Open the browser

A Work task can open the browser panel. The live surface lets you inspect what the agent sees. Browser availability depends on account permissions and a working runtime.


## Take control

Select Take control before entering text or interacting manually. Use Return to OwnCMD when you are finished. The browser address field and navigation controls are enabled for human control.

1. Open the browser panel in the Work conversation.
2. Select Take control.
3. Click, type, paste, scroll, or navigate as needed.
4. Select Return to OwnCMD to let the agent continue.

## Mobile and desktop display

Display offers Auto, Desktop, and Mobile. Auto fits your device. Changing the display does not reload the website; reload if a site serves a separate mobile version. Touch scrolling and a remote keyboard support smaller screens.


## Stopping and hiding

Hiding the preview and stopping the browser are different actions. Use Stop the browser when you intend to close the runtime rather than merely hide its panel.


## A website-login walkthrough

Start the Work task and open the browser panel when the website is available. Select Take control before entering your information. Navigate to the website’s legitimate login form, complete the required steps, and confirm that the expected signed-in page is visible. Select Return to OwnCMD and tell the agent what it can continue doing.

The browser is the task’s remote browser, not the browser application on your phone or laptop. Logging in to a site locally does not automatically log this browser in. Existing saved OwnCMD browser sessions may help, but the website can invalidate them at any time. If the login redirects or requests another challenge, finish that interaction before returning control.


## Display and input troubleshooting

Use Auto when you want the view to fit your device, Desktop to inspect a wider layout, and Mobile to inspect the mobile display. A page may choose a mobile variant only at navigation or reload, so changing Display alone is not always sufficient. The control tooltip explicitly calls out this behavior.

If clicking or typing appears ineffective, check who has control. The browser address field and direct interaction controls may be disabled while the agent is driving. On small screens, use the remote keyboard and scroll the live surface. Do not confuse scrolling the surrounding OwnCMD page with scrolling the website inside the remote view.


## Keep control transitions clear

When you take control, complete the manual step and return control deliberately. Tell OwnCMD what changed, especially if you selected an account, changed a form field, or navigated to a different page. This reduces the chance that the agent continues from an assumption about an earlier screen.

Use Stop the browser when finished with the browser runtime; closing or hiding its panel is only a display action. A website can block automation, expire a session, or refuse a request regardless of browser availability. For a stalled page, inspect the visible website error and current URL before repeatedly asking the agent to retry. Do not interpret a live screenshot as evidence that the final submission succeeded; verify the website’s confirmation state.

