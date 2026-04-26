const fs = require("node:fs");
const path = require("node:path");

const DEV_ENV_KEYS = new Set([
  "AITEACHME_BACKEND_PORT",
  "AITEACHME_FRONTEND_PORT",
]);
const LOCAL_HOST = "127.0.0.1";

function repoRoot() {
  return path.resolve(__dirname, "..", "..");
}

function parseDotEnvValue(rawValue) {
  const value = rawValue.trim();
  if (
    (value.startsWith("\"") && value.endsWith("\"")) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function loadRepoDevEnv() {
  const envPath = path.join(repoRoot(), ".env");
  if (!fs.existsSync(envPath)) {
    return;
  }

  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match || !DEV_ENV_KEYS.has(match[1]) || process.env[match[1]]) {
      continue;
    }
    process.env[match[1]] = parseDotEnvValue(match[2]);
  }
}

function resolveDevPorts() {
  const backendPort = process.env.AITEACHME_BACKEND_PORT || "9020";
  const frontendPort = process.env.AITEACHME_FRONTEND_PORT || "5180";

  return {
    backendPort,
    backendUrl: `http://${LOCAL_HOST}:${backendPort}`,
    frontendPort,
    frontendUrl: `http://${LOCAL_HOST}:${frontendPort}`,
  };
}

module.exports = {
  loadRepoDevEnv,
  resolveDevPorts,
};
