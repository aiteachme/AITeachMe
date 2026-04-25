const http = require("node:http");
const https = require("node:https");

const { loadRepoDevEnv, resolveDevPorts } = require("./dev-env.cjs");

loadRepoDevEnv();

const { frontendUrl } = resolveDevPorts();
const deadline = Date.now() + 30_000;

function requestOnce(url) {
  return new Promise((resolve) => {
    const client = url.startsWith("https:") ? https : http;
    const request = client.get(url, { timeout: 1_000 }, (response) => {
      response.resume();
      resolve(response.statusCode && response.statusCode < 500);
    });

    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

async function waitForServer() {
  while (Date.now() < deadline) {
    if (await requestOnce(frontendUrl)) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }

  throw new Error(`Timed out waiting for ${frontendUrl}`);
}

waitForServer().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
