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

// Timeline matched to the ElevenLabs narration in narration/ (a 0.5 s, b 11 s, c 26 s, d 42.8 s, e 53 s).
const t0 = Date.now();
const at = async (sec) => { const ms = t0 + sec * 1000 - Date.now(); if (ms > 0) await wait(ms); };

// 1. Storm-week replay (narration a + b).
await p.goto("http://127.0.0.1:3000/replay", { waitUntil: "load" });
await at(12.5);
await p.locator("label", { hasText: "FIFO (oldest first)" }).click();
await at(17.5);
await p.locator("label", { hasText: /^SnowTech$/ }).click();
await at(20.5);
await p.getByRole("button", { name: "Next day" }).click();
await at(22.5);
await p.getByRole("button", { name: "Next day" }).click();

// 2. Live ops + voice ticket by landmark (narration c).
await at(25.3);
await p.goto("http://127.0.0.1:3000/", { waitUntil: "load" });
await at(30.5);
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
console.log("voice ticket:", res.status, JSON.stringify(await res.json()).slice(0, 120));

// 3. Disruption (narration d).
await at(42.8);
await p.getByRole("button", { name: /3 crews out/ }).click();
await at(51);
await p.getByRole("button", { name: /Restore crews/ }).click();

// 4. How it works (narration e).
await at(52.8);
await p.goto("http://127.0.0.1:3000/about", { waitUntil: "load" });
await at(55);
for (let y = 0; y < 6; y++) {
  await p.mouse.wheel(0, 300);
  await wait(900);
}
await at(64);

const video = p.video();
await ctx.close();
await browser.close();
const file = await video.path();
renameSync(file, `${OUT}snowtech-demo.webm`);
console.log("saved", `${OUT}snowtech-demo.webm`, readdirSync(OUT));
