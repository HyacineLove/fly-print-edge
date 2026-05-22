export function initTouchRestrictions() {
  try {
    const root = document.documentElement;
    const body = document.body;

    if (root) {
      root.style.touchAction = "none";
      root.style.overscrollBehavior = "none";
      root.style.userSelect = "none";
      root.style.webkitUserSelect = "none";
      root.style.msUserSelect = "none";
    }

    if (body) {
      body.style.touchAction = "none";
      body.style.overscrollBehavior = "none";
      body.style.userSelect = "none";
      body.style.webkitUserSelect = "none";
      body.style.msUserSelect = "none";
    }

    window.addEventListener(
      "touchstart",
      (e) => {
        if (e.touches && e.touches.length > 1) {
          e.preventDefault();
        }
      },
      { passive: false }
    );

    window.addEventListener(
      "touchmove",
      (e) => {
        e.preventDefault();
      },
      { passive: false }
    );

    window.addEventListener(
      "dblclick",
      (e) => {
        e.preventDefault();
      },
      true
    );

    window.addEventListener(
      "contextmenu",
      (e) => {
        e.preventDefault();
      },
      true
    );

    window.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
      },
      { passive: false }
    );

    ["gesturestart", "gesturechange", "gestureend"].forEach((type) => {
      window.addEventListener(
        type,
        (e) => {
          e.preventDefault();
        },
        { passive: false }
      );
    });
  } catch {
    // Ignore touch-guard failures to avoid blocking the page.
  }
}
