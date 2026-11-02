// Copy only public source/config inputs. Never touch the running frontend .next.
import { cp, mkdir, symlink } from "node:fs/promises";
import path from "node:path";

const frontend = process.cwd();
const target = path.resolve(frontend, "../.tmp/order-desk-phase4/frontend");
await mkdir(target, { recursive: true });
for (const item of ["src", "public", "scripts", "e2e", "package.json", "package-lock.json", "tsconfig.json", "next-env.d.ts", "next.config.ts", "postcss.config.mjs", "eslint.config.mjs"]) {
  await cp(path.join(frontend, item), path.join(target, item), { recursive: true });
}
try {
  await symlink(path.join(frontend, "node_modules"), path.join(target, "node_modules"), "junction");
} catch (error) {
  if (error.code !== "EEXIST") throw error;
}
console.log(`Isolated source preview: ${target}`);
