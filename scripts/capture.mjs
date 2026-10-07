#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

function args(argv) {
  const result = {};
  const allowed = new Set(['keyword', 'urls', 'out', 'color', 'width', 'height', 'dpr']);
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '');
    if (!argv[i].startsWith('--') || !allowed.has(key) || argv[i + 1] === undefined) {
      throw new Error(`Unknown/incomplete argument: ${argv[i]}`);
    }
    result[key] = argv[i + 1];
  }
  for (const key of ['keyword', 'urls', 'out']) {
    if (!result[key]?.trim()) throw new Error(`Required: --${key}`);
  }
  return result;
}

async function run() {
  const opt = args(process.argv.slice(2));
  const width = Number(opt.width ?? 1920), height = Number(opt.height ?? 1600);
  const dpr = Number(opt.dpr ?? 1.5), color = opt.color ?? '#3aa8ff';
  if (![width, height].every(n => Number.isInteger(n) && n >= 400 && n <= 4096)
      || !Number.isFinite(dpr) || dpr < 1 || dpr > 3 || !/^#[0-9a-f]{6}$/i.test(color)) {
    throw new Error('Invalid dimensions, DPR or six-digit highlight color');
  }
  const input = JSON.parse(await fs.readFile(opt.urls, 'utf8'));
  if (!Array.isArray(input) || !input.length || input.some(u => typeof u !== 'string')) {
    throw new Error('URL file must be a nonempty JSON array of strings');
  }
  const urls = [...new Set(input)];
  for (const raw of urls) {
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
      throw new Error(`Only public HTTP(S) URLs without credentials: ${raw}`);
    }
  }
  const out = path.resolve(opt.out);
  try { await fs.access(out); throw new Error(`Output already exists: ${out}`); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const modulePath = process.env.JL_PLAYWRIGHT_MODULE;
  const {chromium} = await import(modulePath ? pathToFileURL(path.resolve(modulePath)).href : 'playwright');
  const browser = await chromium.launch({headless: true,
    ...(process.env.JL_BROWSER_EXECUTABLE ? {executablePath: process.env.JL_BROWSER_EXECUTABLE} : {})});
  await fs.mkdir(path.join(out, 'screenshots'), {recursive: true});
  const manifest = {keyword: opt.keyword, highlight_color: color,
    captured_at: new Date().toISOString(), captures: [], failures: []};
  try {
    for (const url of urls) {
      const context = await browser.newContext({viewport: {width, height}, deviceScaleFactor: dpr});
      const page = await context.newPage();
      try {
        const response = await page.goto(url, {waitUntil: 'domcontentloaded', timeout: 45000});
        if (response && response.status() >= 400) throw new Error(`HTTP ${response.status()}`);
        await page.waitForTimeout(800);
        await page.evaluate(() => Promise.race([document.fonts.ready,
          new Promise(resolve => setTimeout(resolve, 3000))]));
        await page.addStyleTag({content: 'html,body,* {scroll-behavior:auto !important;}'});
        await page.evaluate(keyword => {
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          const candidates = [];
          let node;
          while ((node = walker.nextNode())) {
            const parent = node.parentElement;
            if (!parent || parent.closest('script,style,noscript,svg,textarea,input,select,[hidden],[aria-hidden="true"]')) continue;
            const style = getComputedStyle(parent);
            if (style.visibility !== 'visible' || Number(style.opacity) === 0) continue;
            let start = node.textContent.indexOf(keyword);
            while (start !== -1) {
              const range = document.createRange();
              range.setStart(node, start); range.setEnd(node, start + keyword.length);
              const boxes = [...range.getClientRects()].filter(b => b.width > 0 && b.height >= 8);
              if (boxes.length === 1 && boxes[0].width <= innerWidth * 0.85) {
                const rank = (parent.closest('h1') ? 30 : parent.closest('h2,h3') ? 20 : 0)
                  + (parent.closest('article,main,[role="main"]') ? 10 : 0)
                  - (boxes[0].height > 44 ? 45 : 0)
                  - (parent.closest('nav,footer,header,aside') ? 20 : 0);
                candidates.push({node, start, range, rank});
              }
              start = node.textContent.indexOf(keyword, start + keyword.length);
            }
          }
          candidates.sort((a, b) => b.rank - a.rank);
          for (const item of candidates.slice(0, 60)) {
            item.node.parentElement.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
            const b = item.range.getBoundingClientRect();
            const hit = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
            const parent = item.node.parentElement;
            if (b.x < 4 || b.y < 4 || b.right > innerWidth - 4 || b.bottom > innerHeight - 4
                || !hit || !(parent.contains(hit) || hit.contains(parent))) continue;
            window.__jlMatch = item;
            return;
          }
          throw new Error('No visible, single-line, unobstructed exact keyword occurrence');
        }, opt.keyword);
        // Allow scroll-triggered layout to settle, then measure again before capture.
        await page.waitForTimeout(600);
        const measured = await page.evaluate(({keyword, color}) => {
          const item = window.__jlMatch;
          if (!item?.node?.isConnected || item.range.toString() !== keyword) {
            throw new Error('Selected occurrence changed during layout');
          }
          const boxes = [...item.range.getClientRects()].filter(b => b.width > 0 && b.height >= 8);
          if (boxes.length !== 1) throw new Error('Selected occurrence wrapped during layout');
          const b = boxes[0], parent = item.node.parentElement;
          const hit = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
          if (b.x < 4 || b.y < 4 || b.right > innerWidth - 4 || b.bottom > innerHeight - 4
              || !hit || !(parent.contains(hit) || hit.contains(parent))) {
            throw new Error('Selected occurrence obstructed or outside viewport after layout');
          }
          const overlay = document.createElement('div');
          overlay.id = 'text-match-cut-highlight';
          Object.assign(overlay.style, {position: 'fixed', left: `${b.x - 2}px`, top: `${b.y - 1}px`,
            width: `${b.width + 4}px`, height: `${b.height + 2}px`, background: color,
            opacity: '0.32', pointerEvents: 'none', zIndex: '2147483647'});
          document.body.append(overlay);
          return {box: {x: b.x, y: b.y, width: b.width, height: b.height},
            context: item.node.textContent.slice(Math.max(0, item.start - 160),
              item.start + keyword.length + 200).replace(/\s+/g, ' ').trim(),
            selected_text: item.range.toString(), title: document.title, url: location.href};
        }, {keyword: opt.keyword, color});
        const id = String(manifest.captures.length + 1).padStart(3, '0');
        const relative = `screenshots/${id}.png`;
        await page.screenshot({path: path.join(out, relative), animations: 'disabled'});
        const png = await fs.readFile(path.join(out, relative));
        const imageWidth = png.readUInt32BE(16), imageHeight = png.readUInt32BE(20);
        const sx = imageWidth / width, sy = imageHeight / height;
        manifest.captures.push({id, requested_url: url, url: measured.url, title: measured.title,
          context: measured.context, selected_text: measured.selected_text, image: relative,
          image_width: imageWidth, image_height: imageHeight,
          keyword_box: {x: measured.box.x * sx, y: measured.box.y * sy,
            width: measured.box.width * sx, height: measured.box.height * sy},
          captured_at: new Date().toISOString()});
        console.log(`${id}: captured ${measured.url}`);
      } catch (error) {
        manifest.failures.push({url, reason: error.message});
        console.log(`Skipped ${url}: ${error.message.split('\n')[0]}`);
      } finally { await context.close(); }
      await fs.writeFile(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2));
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({captures: manifest.captures.length, failures: manifest.failures.length,
    manifest: path.join(out, 'manifest.json')}));
  if (!manifest.captures.length) process.exitCode = 2;
}

run().catch(error => {console.error(error.message); process.exitCode = 1;});
