#!/usr/bin/env node
import { spawn } from 'node:child_process'
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
  ? path.join(projectRoot, 'data/firefox_profile')
  : path.join(projectRoot, 'data/browser_profile')

console.log(`Using system ${browser.type}: ${browser.path}`)
console.log(`Profile: ${profileDir}`)
console.log('')
console.log('  1. Log in to ChatGPT in the browser window')
console.log('  2. Once you see the chat UI, close the browser window manually')
console.log('  3. Your session will be saved automatically')
console.log('')

const args = browser.type === 'chromium'
  ? [
      `--user-data-dir=${profileDir}`,
      '--password-store=basic',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-blink-features=AutomationControlled',
      'https://chatgpt.com/'
    ]
  : [
      '-profile', profileDir,
      'https://chatgpt.com/'
    ]

const child = spawn(browser.path, args, { stdio: 'inherit' })

child.on('close', (code) => {
  console.log(`\nBrowser closed. You can now run: make start-proxy`)
})

