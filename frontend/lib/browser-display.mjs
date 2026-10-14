// Detect the client device, not the width of a desktop side panel.
export function mobileClient(
  nav = globalThis.navigator,
  win = globalThis.window,
) {
  if (!win) return false;
  return (
    nav?.userAgentData?.mobile === true ||
    /Android.*Mobile|iPhone|iPod/i.test(nav?.userAgent || "") ||
    (nav?.maxTouchPoints > 1 &&
      win.matchMedia?.("(pointer: coarse)").matches &&
      Math.min(
        win.screen?.width || win.innerWidth,
        win.screen?.height || win.innerHeight,
      ) < 600)
  );
}
export function displaySize(width, height, mobile = mobileClient()) {
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width < 1 ||
    height < 1
  )
    return null;
  const scale = Math.min(1, 1920 / width, 1200 / height);
  return {
    width: Math.max(320, Math.round(width * scale)),
    height: Math.max(240, Math.round(height * scale)),
    mobile,
  };
}
export function clientDisplay() {
  if (typeof window === "undefined")
    return { width: 1152, height: 720, mobile: false };
  return displaySize(
    window.innerWidth,
    window.visualViewport?.height || window.innerHeight,
  );
}
export function previewDisplay(
  width,
  height,
  mode = "auto",
  phone = mobileClient(),
) {
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width < 1 ||
    height < 1
  )
    return null;
  const mobile = mode === "mobile" || (mode === "auto" && phone);
  // Desktop side panels are viewers, not emulated phones. Keep a usable desktop
  // layout and fit the image; full-screen then naturally uses the larger area.
  let remoteWidth = Math.min(
    1920,
    Math.max(
      320,
      Math.round(
        mobile
          ? Math.min(width, mode === "mobile" ? 430 : 1920)
          : Math.max(mode === "desktop" ? 1280 : 960, width),
      ),
    ),
  );
  // Compute height from the bounded width. Tall side panels need a taller remote
  // viewport, not independent dimension clamps that introduce letterboxing.
  if ((height * remoteWidth) / width > 4096)
    remoteWidth = Math.max(320, Math.round((4096 * width) / height));
  return {
    width: remoteWidth,
    height: Math.min(
      4096,
      Math.max(240, Math.round((height * remoteWidth) / width)),
    ),
    mobile,
  };
}
export function framePoint(rect, width, height, x, y) {
  return {
    x: Math.max(0, Math.min(width - 1, ((x - rect.left) * width) / rect.width)),
    y: Math.max(
      0,
      Math.min(height - 1, ((y - rect.top) * height) / rect.height),
    ),
  };
}
