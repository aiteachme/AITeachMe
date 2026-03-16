import { setupWorker } from "msw/browser";
import { handlers } from "./index";

export const worker = setupWorker(...handlers);
