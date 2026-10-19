import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distRoot = resolve(projectRoot, "dist");

await rm(distRoot, { recursive: true, force: true });
await mkdir(resolve(distRoot, "server"), { recursive: true });
await mkdir(resolve(distRoot, ".openai"), { recursive: true });
await build({
  entryPoints: [resolve(projectRoot, "worker/index.js")],
  outfile: resolve(distRoot, "server/index.js"),
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  minify: false,
});
await cp(resolve(projectRoot, ".openai/hosting.json"), resolve(distRoot, ".openai/hosting.json"));

console.log(`Built ${distRoot}`);
