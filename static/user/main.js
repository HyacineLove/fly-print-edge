import { renderCommonText, startClockLoop } from "./modules/shared/runtime.js";
import { initTouchRestrictions } from "./modules/shared/touch-guard.js";
import { initDonePage } from "./modules/pages/done.js";
import { initLoginPage } from "./modules/pages/login.js";
import { initPreviewPage } from "./modules/pages/preview.js";
import { initPrintingPage } from "./modules/pages/printing.js";

const page = document.body?.dataset?.page || "";

initTouchRestrictions();
renderCommonText(page);
startClockLoop();

if (page === "login") {
  initLoginPage();
}

if (page === "preview") {
  initPreviewPage();
}

if (page === "printing") {
  initPrintingPage();
}

if (page === "done") {
  initDonePage();
}
