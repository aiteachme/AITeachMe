import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

async function prepare() {
  if (import.meta.env.VITE_USE_MOCK === "true") {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  }
}

prepare().then(() => {
  ReactDOM.createRoot(document.getElementById("app")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
});
