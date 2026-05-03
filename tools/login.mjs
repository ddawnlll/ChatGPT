#!/usr/bin/env node
import { chromium, firefox } from 'playwright'
import process from 'node:process'
import path from 'node:path'
import fs from 'node:fs'

const projectRoot = new URL('..', import.meta.url).pathname

// Detect system browser
const BROWSER_CANDIDATES = [
  { type: 'chromium', path: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' },
  { type: 'chromium', path: '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser' },
  { type: 'chromium', path: '/Applications/Chromium.app/Contents/MacOS/Chromium' },
  { type: 'firefox',  path: '/Applications/Firefox.app/Contents/MacOS/firefox' },
]

function findBrowser() {
  // Allow override via env
  const envPath = process.env.CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH
  if (envPath && fs.existsSync(envPath)) {
    const type = envPath.toLowerCase().includes('firefox') ? 'firefox' : 'chromium'
    return { type, path: envPath }
  }
  for (const candidate of BROWSER_CANDIDATES) {
    if (fs.existsSync(candidate.path)) return candidate
  }
  return null
}

const browser = findBrowser()
if (!browser) {
  console.error('No system browser found! Install Google Chrome, Brave, or Firefox.')
  process.exit(1)
}

const profileDir = browser.type === 'firefox'
  ? `${projectRoot}data/firefox_profile`
  : `${projectRoot}data/browser_profile`

console.log(`Using system ${browser.type}: ${browser.path}`)
console.log(`Profile: ${profileDir}`)
console.log('')
console.log('  1. Log in to ChatGPT in the browser window')
console.log('  2. Once you see the chat UI, close the browser window')
console.log('  3. Your session will be saved automatically')
console.log('')

const engine = browser.type === 'firefox' ? firefox : chromium

const launchOptions = {
  headless: false,
  executablePath: browser.path,
  viewport: { width: 1440, height: 960 },
  args: browser.type === 'chromium'
    ? ['--password-store=basic', '--no-first-run', '--no-default-browser-check', '--disable-blink-features=AutomationControlled']
    : [],
}

const context = await engine.launchPersistentContext(profileDir, launchOptions)
const page = context.pages()[0] || await context.newPage()
await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded' })

console.log('Browser opened. Waiting for you to log in and close the window...')

await new Promise(resolve => {
  context.on('close', resolve)
})

console.log('Session saved! You can now run: make start-proxy')
