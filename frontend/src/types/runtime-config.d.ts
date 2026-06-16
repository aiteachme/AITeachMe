export {};

declare global {
  interface Window {
    __AITEACHME_RUNTIME_CONFIG__?: Record<string, string | undefined>;
  }
}
