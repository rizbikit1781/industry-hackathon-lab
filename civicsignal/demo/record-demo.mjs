// Records a silent ~75 s SnowTech demo at 1920x1080: storm-week replay, a voice ticket
// arriving by landmark (sent to the API exactly as the ElevenLabs webhook would), then a
// disruption replan. Output: demo-video/<random>.webm (renamed to snowtech-demo.webm).
import { chromium } from "playwright";
import { readFileSync, readdirSync, renameSync, mkdirSync } from "node:fs";

const ROOT = "/Users/caelan/code/hackathon/civicsignal";
const OUT = new URL("./", import.meta.url).pathname;
const env = Object.fromEntries(
  readFileSync(`${ROOT}/.env`, "utf8").split("\n").filter((l) => l.includes("=")).map((l) => l.split(/=(.*)/s).slice(0, 2)),
);

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
});
const p = await ctx.newPage();
const wait = (ms) => p.waitForTimeout(ms);

// 1. Storm-week replay: oldest-first vs SnowTech, then step through the week.
await p.goto("http://127.0.0.1:3000/replay", { waitUntil: "load" });
await wait(5000);
await p.locator("label", { hasText: "FIFO (oldest first)" }).click();
await wait(3500);
await p.locator("label", { hasText: /^SnowTech$/ }).click();
await wait(3500);
for (let i = 0; i < 3; i++) {
  await p.getByRole("button", { name: "Next day" }).click();
  await wait(2200);
}

// 2. Live ops: a resident reports by landmark; the ticket lands on the map.
await p.goto("http://127.0.0.1:3000/", { waitUntil: "load" });
await wait(6000);
const res = await fetch("http://127.0.0.1:8000/tickets", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-CivicSignal-Key": env.CIVICSIGNAL_KEY },
  body: JSON.stringify({
    service_name: "sidewalk",
    landmark: "bus loop at the University of Calgary",
    description: "Heavy snowpack on the sidewalk by the bus loop.",
    hazard_notes: "wheelchair user, bus stop",
    source: "voice",
  }),
});
console.log("voice ticket:", res.status, JSON.stringify(await res.json()).slice(0, 200));
await wait(9000);

// 3. Disruption: three crews call in sick, the plan re-solves; then restore.
await p.getByRole("button", { name: /3 crews out/ }).click();
await wait(9000);
await p.getByRole("button", { name: /Restore crews/ }).click();
await wait(7000);

// 4. How it works, scrolled slowly.
await p.goto("http://127.0.0.1:3000/about", { waitUntil: "load" });
await wait(3000);
for (let y = 0; y < 6; y++) {
  await p.mouse.wheel(0, 300);
  await wait(900);
}
await wait(2000);

const video = p.video();
await ctx.close();
await browser.close();
const file = await video.path();
renameSync(file, `${OUT}snowtech-demo.webm`);
console.log("saved", `${OUT}snowtech-demo.webm`, readdirSync(OUT));
