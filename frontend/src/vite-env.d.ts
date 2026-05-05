/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_APP_VERSION?: string;
  readonly VITE_POSTHOG_DEBUG?: string;
  readonly VITE_POSTHOG_ENABLED?: string;
  readonly VITE_POSTHOG_HOST?: string;
  readonly VITE_POSTHOG_SESSION_REPLAY?: string;
  readonly VITE_POSTHOG_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
