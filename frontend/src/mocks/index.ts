import { fileHandlers } from "./handlers/files";
import { chatHandlers } from "./handlers/chat";
import { examHandlers } from "./handlers/exam";
import { profileHandlers } from "./handlers/profile";
import { courseHandlers } from "./handlers/courses";

export const handlers = [
  ...courseHandlers,
  ...fileHandlers,
  ...chatHandlers,
  ...examHandlers,
  ...profileHandlers,
];
