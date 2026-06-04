const { spawnSync } = require("node:child_process");

function quoteArg(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

async function sign(configuration) {
  const template = process.env.AITEACHME_WINDOWS_SIGN_COMMAND;
  if (!template || !template.trim()) {
    throw new Error("AITEACHME_WINDOWS_SIGN_COMMAND is required for the custom Electron Windows sign hook.");
  }

  const targetPath = configuration.path;
  const quotedTarget = quoteArg(targetPath);
  const command = template.includes("%1")
    ? template.replace(/%1/g, quotedTarget)
    : `${template} ${quotedTarget}`;

  console.log(`custom Windows signing: ${targetPath}`);
  const result = spawnSync(command, {
    shell: true,
    stdio: "inherit",
    windowsHide: true,
  });

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`custom Windows signing failed with exit code ${result.status}`);
  }
}

exports.default = sign;
exports.sign = sign;
