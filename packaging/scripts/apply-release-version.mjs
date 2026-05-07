import fs from "node:fs";

const version = process.argv[2] || process.env.RELEASE_VERSION;

if (!version || !/^\d+\.\d+\.\d+(?:-(?:alpha|beta)\.\d+)?$/.test(version)) {
  throw new Error(`Invalid release version: ${version || "<empty>"}`);
}

function updateJson(path, updater) {
  const data = JSON.parse(fs.readFileSync(path, "utf8"));
  updater(data);
  fs.writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`);
}

function replaceInFile(path, replacer) {
  const before = fs.readFileSync(path, "utf8");
  const after = replacer(before);
  fs.writeFileSync(path, after);
}

updateJson("frontend/package.json", (data) => {
  data.version = version;
});

updateJson("frontend/package-lock.json", (data) => {
  data.version = version;
  if (data.packages && data.packages[""]) {
    data.packages[""].version = version;
  }
});

replaceInFile("frontend/openapi.json", (text) => {
  const infoVersionPattern = /("info"\s*:\s*\{[\s\S]*?"version"\s*:\s*)"([^"]+)"/;
  if (!infoVersionPattern.test(text)) {
    throw new Error("Cannot find frontend/openapi.json info.version");
  }
  return text.replace(infoVersionPattern, `$1"${version}"`);
});

replaceInFile("backend/pyproject.toml", (text) =>
  text.replace(/^version = "([^"]+)"/m, `version = "${version}"`),
);

replaceInFile("backend/uv.lock", (text) =>
  text.replace(
    /(\[\[package\]\]\r?\nname = "aiteachme-backend"\r?\nversion = )"([^"]+)"/,
    `$1"${version}"`,
  ),
);
