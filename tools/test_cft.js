import { chromium } from 'playwright';

console.log('Playwright executable:', chromium.executablePath());

const context = await chromium.launchPersistentContext('./data/cft_test_profile', {
  headless: false,
  viewport: { width: 1440, height: 960 },
  args: [
    '--password-store=basic',
    '--no-first-run',
    '--no-default-browser-check'
  ],
});

console.log('launched ok');
await new Promise(r => setTimeout(r, 15000));
await context.close();
