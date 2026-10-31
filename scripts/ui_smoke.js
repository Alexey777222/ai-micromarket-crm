// Local-only UI acceptance check. Run with Playwright installed in NODE_PATH.
const { chromium } = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const base = process.env.MMC_TEST_URL || 'http://127.0.0.1:8019';
  assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Local demo only');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
    await page.goto(base);
    assert(page.url().includes('/accounts/login/'));
    await page.getByLabel('Имя пользователя:').fill('demo');
    await page.getByLabel('Пароль:').fill('demo12345');
    await Promise.all([page.waitForURL(base + '/'), page.getByRole('button', { name: 'Войти', exact: true }).click()]);
    for (const section of ['fridges', 'products', 'stock', 'batches', 'sales', 'writeoffs', 'forecasts']) {
      const response = await page.goto(base + '/records/' + section + '/');
      assert.equal(response.status(), 200, section);
      assert(await page.locator('tbody tr').count() > 0);
    }
    await page.goto(base + '/records/products/');
    await page.getByLabel('Поиск', { exact: true }).fill('Вода');
    await Promise.all([page.waitForURL(/q=/), page.getByRole('button', { name: 'Найти', exact: true }).click()]);
    assert.equal(await page.locator('tbody tr').count(), 1);
    await page.goto(base + '/');
    for (let i = 0; i < 2; i++) {
      await Promise.all([
        page.waitForResponse(r => r.url().includes('/forecasts/generate/') && r.request().method() === 'POST'),
        page.getByRole('button', { name: 'Рассчитать пополнение' }).click(),
      ]);
      await page.waitForLoadState('networkidle');
    }
    if (process.env.MMC_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MMC_SCREENSHOT_DIR, 'desktop.png'), fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    for (const route of ['/', '/records/stock/', '/records/sales/']) {
      await page.goto(base + route);
      const noPageOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
      assert(noPageOverflow, 'Mobile horizontal overflow: ' + route);
    }
    if (process.env.MMC_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MMC_SCREENSHOT_DIR, 'mobile.png'), fullPage: true });
    }
    await Promise.all([page.waitForURL(/accounts\/login/), page.getByRole('button', { name: 'Выйти', exact: true }).click()]);
    await page.goto(base + '/records/sales/');
    assert(page.url().includes('/accounts/login/'));
    console.log('UI OK: login, 7 screens, search, two recalculations, 390px viewport, logout and denied anonymous access.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
