/**
 * 通用 Web 页面检查脚本（Playwright CLI）。
 *
 * 用于 AI 评估模式中的 Web UI 自动化验证。参数化设计，不绑定任何特定页面。
 *
 * 用法:
 *   node tools/web_check.mjs \
 *     --url http://localhost:10006/suggest \
 *     --click "button:has-text('生成选题建议')" \
 *     --wait-selector ".suggest-card, .empty-state" \
 *     --extract ".suggest-card .card-title" \
 *     --screenshot "data/eval_reports/web-{ts}.png" \
 *     --timeout 120000
 *
 * 参数:
 *   --url            页面地址（必填）
 *   --click          要点击的元素选择器（可选）
 *   --wait-selector  等待出现的元素，逗号分隔，任一出现即继续（必填）
 *   --extract        提取文本的元素选择器（可选）
 *   --screenshot     截图保存路径，{ts} 替换为时间戳（可选）
 *   --timeout        超时毫秒数（默认 30000）
 *
 * 退出码:
 *   0  检查通过（找到了有效的页面内容）
 *   1  检查失败（页面错误或超时）
 *   2  跳过（Playwright 未安装）
 */

// ── 参数解析 ──────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { timeout: 30000 };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--url":          opts.url = args[++i];          break;
      case "--click":        opts.click = args[++i];        break;
      case "--wait-selector": opts.waitSelector = args[++i]; break;
      case "--extract":      opts.extract = args[++i];      break;
      case "--screenshot":   opts.screenshot = args[++i];   break;
      case "--timeout":      opts.timeout = parseInt(args[++i], 10); break;
    }
  }
  return opts;
}

const opts = parseArgs();

if (!opts.url || !opts.waitSelector) {
  console.error("Usage: node tools/web_check.mjs --url <url> --wait-selector <sel> [--click <sel>] [--extract <sel>] [--screenshot <path>] [--timeout <ms>]");
  process.exit(1);
}

// ── Playwright 懒加载 ──────────────────────────────────────

let chromium;
try {
  const pw = await import("playwright");
  chromium = pw.chromium;
} catch (e) {
  console.log(JSON.stringify({
    passed: false,
    skipped: true,
    reason: "Playwright 未安装。安装命令: npm install playwright && npx playwright install chromium",
    error: e.message,
  }));
  process.exit(2);
}

// ── 主逻辑 ─────────────────────────────────────────────────

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await context.newPage();

let screenshotPath = null;
let extractedTexts = [];
let hasError = false;
let errorText = "";

try {
  // 1. 导航
  await page.goto(opts.url, { waitUntil: "networkidle", timeout: opts.timeout });

  // 2. 点击（可选）
  if (opts.click) {
    const btn = page.locator(opts.click).first();
    if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await btn.click();
    } else {
      // 按钮不可见不算失败，可能页面已经加载了结果
      console.error(`[web_check] 按钮不可见: ${opts.click}，跳过点击`);
    }
  }

  // 3. 等待结果
  const selectors = opts.waitSelector.split(",").map(s => s.trim());
  try {
    await page.waitForFunction(
      (sels) => sels.some(s => document.querySelector(s)),
      selectors,
      { timeout: opts.timeout }
    );
  } catch (e) {
    hasError = true;
    errorText = `等待超时 (${opts.timeout}ms): 未出现 ${opts.waitSelector}`;
  }

  // 4. 提取文本（可选）
  if (opts.extract && !hasError) {
    extractedTexts = await page.evaluate((sel) => {
      const els = document.querySelectorAll(sel);
      return Array.from(els).map(el => el.textContent?.trim() || "");
    }, opts.extract);
  }

  // 检查是否有错误状态
  const errorSelector = ".n-empty, .empty-state, [class*='error']";
  const errorEl = await page.$(errorSelector);
  if (errorEl) {
    const text = await errorEl.textContent().catch(() => "");
    if (text && (text.includes("未发现") || text.includes("失败") || text.includes("错误"))) {
      hasError = true;
      errorText = text.trim().slice(0, 200);
    }
  }

  // 5. 截图（可选）
  if (opts.screenshot) {
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    screenshotPath = opts.screenshot.replace("{ts}", ts);
    // 确保目录存在
    const dir = screenshotPath.substring(0, screenshotPath.lastIndexOf("/"));
    if (dir) {
      const fs = await import("fs");
      fs.mkdirSync(dir, { recursive: true });
    }
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }

} catch (e) {
  hasError = true;
  errorText = e.message;
} finally {
  await browser.close();
}

// ── 输出结果 ───────────────────────────────────────────────

const passed = !hasError;
const result = {
  passed,
  url: opts.url,
  extractedTexts,
  extractedCount: extractedTexts.length,
  hasError,
  error: errorText || null,
  screenshotPath,
};

console.log(JSON.stringify(result, null, 2));
process.exit(passed ? 0 : 1);
