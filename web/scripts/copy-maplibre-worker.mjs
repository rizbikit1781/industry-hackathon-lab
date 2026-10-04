// MapLibre GL v6 loads its web worker as a sibling ES module of the main bundle
// (new URL("./maplibre-gl-worker.mjs", import.meta.url)). Bundlers rewrite import.meta.url,
// so serve the worker (and the shared chunk it imports) from public/ and point setWorkerUrl at it.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "maplibre-gl", "dist");
const dst = join(root, "public", "maplibre");
mkdirSync(dst, { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) copyFileSync(join(src, f), join(dst, f));
console.log("maplibre worker copied to public/maplibre/");
