const DASHBOARD_ROUTES = ["/", "/simulation", "/analysis"];

function currentRouteIndex() {
  const path = window.location.pathname;
  if (path === "/simulation") {
    return 1;
  }
  if (path === "/analysis") {
    return 2;
  }
  return 0;
}

function navigateBySwipe(deltaX, deltaY) {
  const absX = Math.abs(deltaX);
  const absY = Math.abs(deltaY);
  if (absX < 80 || absY > absX * 0.65) {
    return;
  }

  const current = currentRouteIndex();
  const direction = deltaX < 0 ? 1 : -1;
  const next = (current + direction + DASHBOARD_ROUTES.length) % DASHBOARD_ROUTES.length;
  window.location.href = DASHBOARD_ROUTES[next];
}

let swipeStartX = null;
let swipeStartY = null;

window.addEventListener("touchstart", (event) => {
  if (!event.touches || event.touches.length !== 1) {
    swipeStartX = null;
    swipeStartY = null;
    return;
  }
  swipeStartX = event.touches[0].clientX;
  swipeStartY = event.touches[0].clientY;
}, { passive: true });

window.addEventListener("touchend", (event) => {
  if (swipeStartX === null || swipeStartY === null || !event.changedTouches || event.changedTouches.length !== 1) {
    return;
  }
  const endX = event.changedTouches[0].clientX;
  const endY = event.changedTouches[0].clientY;
  navigateBySwipe(endX - swipeStartX, endY - swipeStartY);
  swipeStartX = null;
  swipeStartY = null;
}, { passive: true });
