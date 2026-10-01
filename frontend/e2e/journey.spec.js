import { expect, test } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const PDF = path.join(here, 'fixtures', 'research.pdf');
const SHOTS = process.env.E2E_SHOTS || path.join(here, '..', 'test-results', 'shots');
const unique = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function register(page, email, name = 'Ada Tester') {
  await page.goto('/register');
  await page.getByLabel('Full name').fill(name);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill('correct horse battery');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

test('full journey: register → upload → ready → ask → stream → cite → persist → logout', async ({ page }) => {
  const email = `ada-${unique()}@example.com`;
  await page.goto('/login');
  await page.screenshot({ path: `${SHOTS}/01-login.png` });
  await register(page, email);
  await page.screenshot({ path: `${SHOTS}/02-empty-workspace.png` });

  // Upload PDF via the hero drop zone's file input
  await page.locator('.dropzone-hero input[type=file]').setInputFiles(PDF);
  const card = page.locator('.doc-card', { hasText: 'research.pdf' });
  await expect(card).toBeVisible();
  await expect(card.getByText('Ready')).toBeVisible({ timeout: 20_000 });
  await expect(card).toContainText('3 chunks');
  await expect(card).toContainText('3 pp');
  await page.screenshot({ path: `${SHOTS}/03-ready.png` });

  // Ask
  await page.getByLabel('Ask a question about your documents').fill('What does photosynthesis convert?');
  await page.keyboard.press('Enter');
  await expect(page.locator('.rag-status, .streaming-text').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/04-streaming.png` });
  const answer = page.locator('.msg-ai').last();
  await expect(answer).toContainText('Fake answer (E2E mode)', { timeout: 20_000 });
  await expect(page.locator('.caret')).toHaveCount(0, { timeout: 20_000 });

  // Markdown safety in a real browser: no injected image, javascript: link not clickable
  await expect(answer.locator('img')).toHaveCount(0);
  await expect(answer.locator('a[href^="javascript"]')).toHaveCount(0);
  await expect(answer.locator('a[href="https://example.com"]')).toHaveCount(1);

  // Citations exist, map to the real document, and open the real passage
  const chip = answer.locator('.citation-chip').first();
  await expect(chip).toContainText('research.pdf');
  await expect(chip).toContainText('p. ');
  await page.screenshot({ path: `${SHOTS}/05-answer.png` });
  await chip.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.passage')).not.toBeEmpty();
  await page.screenshot({ path: `${SHOTS}/06-citation.png` });
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();

  // Refresh: conversation (from URL) and messages persist
  await expect(page).toHaveURL(/\/chat\/\d+$/);
  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(page.locator('.msg-user')).toContainText('What does photosynthesis convert?');
  await expect(page.locator('.msg-ai').last()).toContainText('Fake answer');
  await expect(page.locator('.conv-item.active')).toContainText('What does photosynthesis convert?');

  // Back/forward
  await page.getByRole('button', { name: 'New chat' }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.goBack();
  await expect(page).toHaveURL(url);
  await page.goForward();
  await expect(page).toHaveURL(/\/chat$/);

  // Logout → protected routes blocked, token revoked server-side
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto(url);
  await expect(page).toHaveURL(/\/login$/);
});

test('wrong password shows a generic error on the form', async ({ page }) => {
  const email = `bob-${unique()}@example.com`;
  await register(page, email);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill('wrong password!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toHaveText('Invalid email or password.');
  await expect(page).toHaveURL(/\/login$/);
});

test('user B sees none of user A’s documents or conversations', async ({ page, browser }) => {
  await register(page, `alice-${unique()}@example.com`, 'Alice');
  await page.locator('.dropzone-hero input[type=file]').setInputFiles({ name: 'alice-private.txt', mimeType: 'text/plain', buffer: Buffer.from(`Alice private ${unique()}`) });
  await expect(page.locator('.doc-card', { hasText: 'alice-private.txt' }).getByText('Ready')).toBeVisible({ timeout: 20_000 });
  await page.getByLabel('Ask a question about your documents').fill('alice secret?');
  await page.keyboard.press('Enter');
  await expect(page.locator('.msg-ai').last()).toContainText('Fake answer', { timeout: 20_000 });
  const aliceConv = page.url();

  const ctx = await browser.newContext();
  const bob = await ctx.newPage();
  await register(bob, `bob2-${unique()}@example.com`, 'Bob');
  await expect(bob.getByText('alice-private.txt')).toHaveCount(0);
  await bob.goto(aliceConv.replace(/^https?:\/\/[^/]+/, ''));
  await expect(bob.getByRole('alert')).toContainText(/no longer exists|not found/i);
  await expect(bob.locator('.msg')).toHaveCount(0);
  await ctx.close();
});

test('invalid file types are refused without fake success', async ({ page }) => {
  await register(page, `carl-${unique()}@example.com`);
  await page.locator('.dropzone-hero input[type=file]').setInputFiles({ name: 'evil.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') });
  await expect(page.getByRole('alert')).toContainText('Only PDF, TXT and MD');
  // Renamed binary passes the UI precheck but the server rejects it, and the error is shown
  await page.locator('.dropzone-hero input[type=file]').setInputFiles({ name: 'fake.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a pdf') });
  await expect(page.locator('.doc-card', { hasText: 'fake.pdf' })).toContainText('not a valid PDF');
});

test('mobile layout keeps the form and composer usable @mobile', async ({ page }) => {
  await page.goto('/login');
  const card = page.locator('.auth-card');
  await expect(card).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/m1-login.png` });
  // the form controls are not covered by decorative objects
  const box = await page.getByRole('button', { name: 'Sign in' }).boundingBox();
  const topEl = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest('button')?.textContent, {
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
  });
  expect(topEl).toContain('Sign in');
  await register(page, `mo-${unique()}@example.com`);
  await page.screenshot({ path: `${SHOTS}/m2-workspace.png` });
  await page.getByRole('button', { name: 'Open menu' }).click();
  await expect(page.locator('.sidebar')).toBeInViewport();
  await page.screenshot({ path: `${SHOTS}/m3-drawer.png` });
});

test('reduced motion disables floating animation', async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await page.goto('/login');
  const anim = await page.locator('.float').first().evaluate((el) => getComputedStyle(el).animationName);
  expect(anim).toBe('none');
  await ctx.close();
});
