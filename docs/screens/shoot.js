// Takes the README screenshots of the web interface (Playwright, Node).
//
//   node docs/screens/shoot.js URL OUT_FOLDER en|ru
//
// The English (public) set is taken without the MS4X Wiki, so no wiki text ends
// up in the public repository: serve_demo.py without a wiki file and NO_WIKI=1.
//
// URL comes from serve_demo.py. Pictures: OUT_FOLDER/<lang>-<screen>.png
const path = require("path");
const pw = process.env.PLAYWRIGHT_PATH || "playwright";
const { chromium } = require(pw);

const [url, out, lang] = process.argv.slice(2);

(async () => {
  const browser = await chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  const shot = name => page.screenshot({ path: path.join(out, `${lang}-${name}.png`) });
  const nav = async v => { await page.click(`#nav button[data-v="${v}"]`); await page.waitForTimeout(400); };
  await page.goto(url);
  await page.waitForSelector("#nav button");

  // compare: the ignition map as a difference, the rev limiter explained on the right
  await nav("cmp");
  await page.click("#btnRun");
  await page.waitForSelector(".row");
  await page.click('.row[data-title="id_n_max_mt__gear"] .t');
  await page.waitForSelector("#drawer.open .pname");
  await page.evaluate(() => { document.querySelector("#view").scrollTop = 0; window.scrollTo(0, 0); });
  await page.waitForTimeout(400);
  await shot("compare-top");
  await page.click('.row[data-title="ip_iga_ron_98_pl_ivvt__n__maf"] .mapbtn');
  await page.waitForSelector(".row .mapbox table.map");
  await page.click('.row[data-title="c_conf_cat"] .t');
  await page.waitForSelector("#drawer.open .pname");
  await page.waitForTimeout(400);
  await shot("compare");

  // browse: VANOS map of one firmware
  await page.keyboard.press("Escape");
  await nav("browse");
  await page.waitForSelector('.row[data-src="read"]');
  await page.click('.row[data-title="ip_cam_sp_tco_1_in_pl__n__maf_iv"] .mapbtn');
  await page.waitForSelector("table.map");
  await page.waitForTimeout(300);
  await shot("browse");

  // different versions + port plan
  await nav("cross");
  await page.click("#btnCross");
  await page.waitForSelector('.row[data-src="xdf"]');
  await page.click('[data-ctab="port"]');
  await page.click("#btnPort");
  await page.waitForSelector(".pill.ok");
  await page.waitForTimeout(300);
  await shot("port");

  // patches
  await nav("patch");
  await page.click("#btnPatch");
  await page.waitForSelector(".prow");
  await page.waitForTimeout(300);
  await shot("patches");

  // reference: the warnings list, first section open (skipped for the public
  // README, whose screenshots are taken without the wiki: NO_WIKI=1)
  if (process.env.NO_WIKI !== "1") {
  await nav("wiki");
  await page.waitForSelector("#btnCaut");
  await page.click("#btnCaut");
  await page.waitForSelector("[data-wsec]");
  await page.click('[data-wsec="0"]');
  await page.waitForSelector(".wikitext h2");
  await page.waitForTimeout(300);
  await shot("wiki");
  }

  // AI assistant: the live server started and checked, the tuning project below
  await nav("ai");
  await page.waitForSelector("[data-ai-add]");
  await page.click('[data-ai="ai_start"]');
  await page.waitForSelector('[data-ai="ai_check"]:not([disabled])');
  await page.click('[data-ai="ai_check"]');
  await page.waitForTimeout(1500);
  // the demo runs on Linux in a temp folder: show a usual Windows path, hide the token
  await page.evaluate(() => {
    const f = document.getElementById("projFolder");
    if (f) f.value = "C:\\Tuning\\E46 330i";
    for (const el of document.querySelectorAll("#view *")) {
      if (el.children.length === 0 && el.textContent.includes("Bearer ")) {
        el.textContent = el.textContent.replace(/Bearer [^"\s]+/, "Bearer …");
      }
    }
  });
  await shot("ai");
  // the car profile: picked from lists, measured gears and Claude's proposal waiting
  await page.evaluate(() => document.getElementById("btnCarCal").closest("section").scrollIntoView());
  await page.waitForTimeout(300);
  await shot("car");

  // edits: the AI draft for firmware B, the ignition change opened as a difference
  await nav("edits");
  await page.click('[data-fwkey="edits"][data-fw="bin_b"]').catch(() => {});
  await page.waitForSelector(".row.edit");
  await page.click('.row.edit[data-title="ip_iga_ron_98_pl_ivvt__n__maf"] .mapbtn');
  await page.waitForSelector(".row.edit .mapbox table.map");
  await page.waitForTimeout(400);
  await shot("edits");

  // logs: the newer log over the ignition map, compared with the one before the flash
  await nav("logs");
  await page.waitForSelector("table.lgmap");
  await page.click('[data-lg="2026-10-07_cruise.csv"]');
  await page.waitForSelector("table.lgmap");
  await page.waitForTimeout(400);
  await shot("logs");
  await page.evaluate(() => document.querySelector("table.lgmap").closest("section").scrollIntoView());
  await page.waitForTimeout(300);
  await shot("logs-map");

  console.log("errors:", errors);
  await browser.close();
})();
