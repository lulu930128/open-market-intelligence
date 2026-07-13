import { cp, mkdir, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";


function argumentValue(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

async function exists(target) {
  try {
    await stat(target);
    return true;
  } catch {
    return false;
  }
}

const root = process.cwd();
const standaloneRoot = path.join(root, ".next", "standalone");
const serverPath = path.join(standaloneRoot, "server.js");
if (!(await exists(serverPath))) {
  throw new Error("Standalone build is missing. Run `npm run build` before production E2E.");
}

const staticSource = path.join(root, ".next", "static");
const staticTarget = path.join(standaloneRoot, ".next", "static");
await mkdir(path.dirname(staticTarget), { recursive: true });
await cp(staticSource, staticTarget, { recursive: true, force: true });

const publicSource = path.join(root, "public");
if (await exists(publicSource)) {
  await cp(publicSource, path.join(standaloneRoot, "public"), {
    recursive: true,
    force: true,
  });
}

process.env.HOSTNAME = argumentValue("--hostname", "127.0.0.1");
process.env.PORT = argumentValue("--port", "3100");
process.chdir(standaloneRoot);
await import(pathToFileURL(serverPath).href);
