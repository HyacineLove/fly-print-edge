import { createAppController } from "./modules/app/app-controller.js";

const app = createAppController({
  mountNode: document.getElementById("app"),
});

void app.start();
