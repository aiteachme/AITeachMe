import { fileHandlers } from "./handlers/files";
import { chatHandlers } from "./handlers/chat";
import { examHandlers } from "./handlers/exam";
import { profileHandlers } from "./handlers/profile";
import { subjectHandlers } from "./handlers/subjects";

export const handlers = [
  ...subjectHandlers,
  ...fileHandlers,
  ...chatHandlers,
  ...examHandlers,
  ...profileHandlers,
];
