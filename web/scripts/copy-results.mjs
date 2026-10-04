// Copy ../data/results.json (storm-week replay) into web/data/ so the app is self-contained when
// only web/ is deployed (Vercel). At runtime lib/server.ts prefers ../data/results.json when it
// exists, so local behaviour is unchanged. If the parent file is missing (e.g. building on
// Vercel), keep the committed copy.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(web, "..", "data", "results.json");
const dst = join(web, "data", "results.json");
if (existsSync(src)) {
  mkdirSync(dirname(dst), { recursive: true });
  copyFileSync(src, dst);
  console.log("results.json copied to web/data/");
} else if (existsSync(dst)) {
  console.log("../data/results.json not found; using existing web/data/results.json");
} else {
  console.warn("no results.json found; /replay will show its empty state");
}
