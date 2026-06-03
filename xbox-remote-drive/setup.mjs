#!/usr/bin/env node
import { chromium } from "playwright-core";

const CDP = process.env.CDP_URL || "http://localhost:9223";
const TARGET = "https://www.xbox.com/en-US/play/consoles";

const INJECT = `
(() => {
  if (window.__hermesPad) return;
  const pad = {
    id: "Xbox 360 Controller (XInput STANDARD GAMEPAD) — Hermes virtual",
    index: 0,
    connected: true,
    timestamp: performance.now(),
    mapping: "standard",
    axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })),
  };
  let state = {
    axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })),
  };
  const fresh = () => ({
    ...pad,
    timestamp: performance.now(),
    axes: [...state.axes],
    buttons: state.buttons.map(b => ({ ...b })),
  });
  const real = navigator.getGamepads.bind(navigator);
  navigator.getGamepads = function () {
    const arr = real();
    arr[0] = fresh();
    return arr;
  };
  for (const k of ["getGamepads", "webkitGetGamepads"]) {
    if (navigator[k] && navigator[k] !== navigator.getGamepads) {
      navigator[k] = navigator.getGamepads;
    }
  }
  window.__hermesPad = {
    press: (i) => { state.buttons[i] = { pressed: true, touched: true, value: 1 }; },
    release: (i) => { state.buttons[i] = { pressed: false, touched: false, value: 0 }; },
    axis: (i, v) => { state.axes[i] = Math.max(-1, Math.min(1, v)); },
    snap: () => fresh(),
  };
  console.log("[hermes] virtual gamepad installed on", location.hostname);
})();
`;

const browser = await chromium.connectOverCDP(CDP);
const ctx = browser.contexts()[0] || (await browser.newContext());
let page = ctx.pages()[0];
if (!page) page = await ctx.newPage();
console.log("[hermes] currently on:", page.url());

if (!page.url().includes("xbox.com/play")) {
  console.log("[hermes] navigating to", TARGET);
  await page.goto(TARGET, { waitUntil: "domcontentloaded", timeout: 60000 });
}

await page.addInitScript(INJECT);
console.log("[hermes] reloading to install gamepad shim...");
await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });

try {
  await page.waitForFunction(() => !!window.__hermesPad, { timeout: 15000 });
  console.log("[hermes] shim installed ✓ on", page.url());
} catch (e) {
  console.log("[hermes] shim not detected yet (page may still be loading):", e.message);
}

console.log("[hermes] done. Sign in + start a game in that window, then run drive.mjs to play.");
process.exit(0);
