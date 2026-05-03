const { chromium } = require('playwright');
const path = require('path');

console.log('--- Playwright Diagnostic ---');
console.log('Playwright Version:', require('playwright/package.json').version);
console.log('Process Arch:', process.arch);
console.log('PLAYWRIGHT_BROWSERS_PATH:', process.env.PLAYWRIGHT_BROWSERS_PATH);
console.log('Resolved Executable Path:', chromium.executablePath());
console.log('-----------------------------');
