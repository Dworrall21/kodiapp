#!/usr/bin/env node
// Xbox Remote Play controller emulator over CDP.
// Connects to a Chrome launched with --remote-debugging-port=9222,
// injects a synthetic Xbox 360 gamepad, and exposes a REPL for
// pressing buttons / moving sticks.

import { chromium } from "playwright-core";
import readline from "node:readline";

const CDP_URL = process.env.CDP_URL || "http://localhost:9222";

// Xbox 360 standard mapping (matches what navigator.getGamepads returns
// under the "standard" mapping Chrome uses for XInput controllers).
const BTN = {
  a: 0, b: 1, x: 2, y: 3,
  lb: 4, rb: 5, lt: 6, rt: 7,
  select: 8, sel: 8, start: 9, sta: 9,
  l3: 10, r3: 11,
  dup: 12, up: 12, ddown: 13, dn: 13, down: 13, dleft: 14, lf: 14, left: 14, dright: 15, rt: 15, right: 15,
  home: 16,
};
const AXIS = { lx: 0, ly: 1, rx: 2, ry: 3 };

function makePad() {
  return {
    id: "Xbox 360 Controller (XInput STANDARD GAMEPAD) — Hermes virtual",
    index: 0,
    connected: true,
    timestamp: performance.now(),
    mapping: "standard",
    axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })),
  };
}

const INJECT = `
(() => {
  if (window.__hermesPad) return;
  const pad = ${JSON.stringify({
    id: "Xbox 360 Controller (XInput STANDARD GAMEPAD) — Hermes virtual",
    mapping: "standard",
  })};
  let state = {
    axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })),
  };
  const fresh = () => ({
    ...pad,
    index: 0,
    connected: true,
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
  // Some sites cache the snapshot. Patch common reads.
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
  console.log("[hermes] virtual gamepad installed");
})();
`;

const HELP = `
Xbox Remote Play controller — commands
  tap <btn>            press + release a button (a b x y lb rb lt rt sel sta l3 r3 up dn lf rt home)
  hold <btn>           press and keep held
  rel <btn>            release a held button
  stick <side> <x> <y> set L/R stick  (side: L|R, x/y: -1..1)
  axis <idx> <v>       raw axis 0..3  (v: -1..1)
  pulse <btn> <ms>     hold for N ms then release
  sequence a;500;b;500  run a list of tap/pause steps, semicolon-separated
  state                dump current state
  list                 list button + axis names
  quit                 exit
`;

async function main() {
  console.log(`[hermes] connecting to ${CDP_URL} ...`);
  const browser = await chromium.connectOverCDP(CDP_URL);
  const contexts = browser.contexts();
  if (!contexts.length) { console.error("[hermes] no browser context"); process.exit(1); }

  let page = null;
  for (const ctx of contexts) {
    for (const p of ctx.pages()) {
      const url = p.url();
      if (url.includes("xbox.com/en-US/play/consoles") || url.includes("xbox.com/play") || url.includes("xboxplay")) {
        page = p; break;
      }
    }
    if (page) break;
  }
  if (!page) {
    console.log("[hermes] no xbox.com/play tab found; using first page");
    page = contexts[0].pages()[0];
  }
  if (!page) { console.error("[hermes] no page"); process.exit(1); }

  console.log(`[hermes] attached to: ${page.url()}`);
  await page.addInitScript(INJECT);
  // Force a reload so the init script runs before the app boots.
  // Skip if the user explicitly disabled it.
  if (process.env.NO_RELOAD !== "1") {
    console.log("[hermes] reloading page to install gamepad shim...");
    await page.reload({ waitUntil: "domcontentloaded" });
  }
  await page.waitForFunction(() => !!window.__hermesPad, { timeout: 15000 });
  console.log("[hermes] virtual gamepad ready. type 'help' for commands.");

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: "xbox> " });
  rl.prompt();

  rl.on("line", async (line) => {
    const raw = line.trim();
    if (!raw) { rl.prompt(); return; }
    const [cmd, ...args] = raw.split(/\s+/);
    try {
      switch (cmd) {
        case "help": case "?": console.log(HELP); break;
        case "list":
          console.log("buttons:", Object.keys(BTN).join(" "));
          console.log("axes:   ", Object.keys(AXIS).map(k => `${k}=${AXIS[k]}`).join(" "));
          break;
        case "quit": case "exit": rl.close(); return;
        case "state":
          console.log(await page.evaluate(() => JSON.stringify(window.__hermesPad.snap(), null, 2)));
          break;
        case "press": case "hold": {
          const i = BTN[args[0]];
          if (i == null) throw new Error(`unknown button ${args[0]}`);
          await page.evaluate((i) => window.__hermesPad.press(i), i);
          console.log(`[hermes] pressed ${args[0]}`);
          break;
        }
        case "rel": case "release": {
          const i = BTN[args[0]];
          if (i == null) throw new Error(`unknown button ${args[0]}`);
          await page.evaluate((i) => window.__hermesPad.release(i), i);
          console.log(`[hermes] released ${args[0]}`);
          break;
        }
        case "tap": {
          const i = BTN[args[0]];
          if (i == null) throw new Error(`unknown button ${args[0]}`);
          const ms = Number(args[1] || 80);
          await page.evaluate((i) => window.__hermesPad.press(i), i);
          await sleep(ms);
          await page.evaluate((i) => window.__hermesPad.release(i), i);
          console.log(`[hermes] tapped ${args[0]} (${ms}ms)`);
          break;
        }
        case "pulse": {
          const i = BTN[args[0]]; const ms = Number(args[1] || 500);
          if (i == null) throw new Error(`unknown button ${args[0]}`);
          await page.evaluate((i) => window.__hermesPad.press(i), i);
          await sleep(ms);
          await page.evaluate((i) => window.__hermesPad.release(i), i);
          console.log(`[hermes] pulsed ${args[0]} for ${ms}ms`);
          break;
        }
        case "stick": {
          const side = (args[0] || "").toUpperCase();
          const x = Number(args[1] || 0);
          const y = Number(args[2] || 0);
          const axisX = side === "L" ? 0 : 2;
          const axisY = side === "L" ? 1 : 3;
          await page.evaluate(([a, b, x, y]) => {
            window.__hermesPad.axis(a, x);
            window.__hermesPad.axis(b, y);
          }, [axisX, axisY, x, y]);
          console.log(`[hermes] ${side} stick = (${x}, ${y})`);
          break;
        }
        case "axis": {
          const i = Number(args[0]); const v = Number(args[1] || 0);
          if (i < 0 || i > 3) throw new Error("axis index 0..3");
          await page.evaluate(([i, v]) => window.__hermesPad.axis(i, v), [i, v]);
          console.log(`[hermes] axis[${i}] = ${v}`);
          break;
        }
        case "sequence": {
          const steps = args.join(" ").split(";");
          for (const s of steps) {
            const tok = s.trim();
            const ms = Number(tok);
            if (!Number.isNaN(ms) && tok !== "") { await sleep(ms); continue; }
            const [k, n] = tok.split(/\s+/);
            const i = BTN[k];
            if (i == null) throw new Error(`unknown ${k}`);
            await page.evaluate((i) => window.__hermesPad.press(i), i);
            await sleep(Number(n || 80));
            await page.evaluate((i) => window.__hermesPad.release(i), i);
            console.log(`[hermes] tap ${k}`);
          }
          break;
        }
        default: console.log(`unknown cmd: ${cmd}. type 'help'`);
      }
    } catch (e) {
      console.error(`[hermes] error: ${e.message}`);
    }
    rl.prompt();
  });

  rl.on("close", () => { console.log("[hermes] bye"); process.exit(0); });
}

main().catch(e => { console.error(e); process.exit(1); });
