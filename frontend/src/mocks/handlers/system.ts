import { HttpResponse, http } from "msw";

const mockSettingsOverview = {
  settings_source: "mock",
  mode: "local",
  sections: [],
  notes: ["Mock 模式使用前端内置设置概览。"],
};

export const systemHandlers = [
  http.post("/api/v1/system/settings", () => {
    return HttpResponse.json({ code: 0, data: mockSettingsOverview });
  }),

  http.patch("/api/v1/system/settings", () => {
    return HttpResponse.json({ code: 0, data: mockSettingsOverview });
  }),
];
