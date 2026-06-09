import { bindConfigActions, loadInitialAdminData } from "./modules/config-actions.js";
import { bindPrinterActions } from "./modules/printer-actions.js";
import { renderAdminApp } from "./modules/render-sections.js";
import { createAdminState } from "./modules/state.js";

const state = createAdminState();
const render = () => renderAdminApp(state);
const { ensurePrintersLoaded } = bindPrinterActions(state, render);

bindConfigActions(state, render, ensurePrintersLoaded);
render();

void loadInitialAdminData(state, render);
