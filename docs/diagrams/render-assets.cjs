// Run from the repository root with Node.js, Playwright and Chromium installed.
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
(async () => {
  const repo = path.resolve(__dirname, '../..');
  const browser = await chromium.launch({ headless: true, ...(process.env.DIAGRAM_BROWSER ? {executablePath: process.env.DIAGRAM_BROWSER} : {}) });
  try {
    for (const [name, height] of [['review-workflow', 1080], ['review-vs-debate', 650]]) {
      const page = await browser.newPage({ viewport: { width: 1200, height }, deviceScaleFactor: 2 });
      const svg = await fs.readFile(path.join(repo, 'docs/assets', `${name}.svg`), 'utf8');
      await page.setContent(`<style>html,body{margin:0;padding:0}svg{display:block}</style>${svg}`);
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: path.join(repo, 'docs/assets', `${name}.png`), fullPage: true });
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
