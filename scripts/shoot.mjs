// Screenshot helper: node scripts/shoot.mjs <outdir> [steps...]  (needs the app on BASE, default :8000)
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
const BASE = process.env.BASE || "http://127.0.0.1:8000";
const out = process.argv[2] || ".";
const steps = process.argv.slice(3);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.log("PAGEERROR", e.message, (e.stack||"").split("\n").slice(0,6).join(" | ")));
page.on("console", (m) => m.type() === "error" && console.log("CONSOLE", m.text()));
await page.goto(BASE + "/");
await page.fill('input[name="username"]', process.env.USER_NAME || "jury");
await page.fill('input[name="password"]', process.env.USER_PASS || "jury");
await page.click("button:has-text('Sign in')");
await page.waitForTimeout(800);
for (const s of steps) {
  const [kind, arg, name] = s.split("|");
  if (kind === "goto") await page.goto(BASE + arg);
  if (kind === "click") await page.click(arg);
  if (kind === "fill") { const [sel, val] = arg.split("=>"); await page.fill(sel, val); }
  if (kind === "wait") await page.waitForTimeout(Number(arg));
  if (kind === "shot") await page.screenshot({ path: `${out}/${arg}.png`, fullPage: name === "full" });
  if (kind === "eval") console.log(await page.evaluate(arg));
}
await browser.close();
