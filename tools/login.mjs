#!/usr/bin/env node
import { spawn } from 'node:child_process'
import process from 'node:process'
import fs from 'node:fs'
import path from 'node:path'
import { getDefaultExecutablePath, getDefaultUserDataDir } from './paths.mjs'

function findBrowser() {
  const envPath = process.env.CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH
  if (envPath && fs.existsSync(envPath)) {
    const type = envPath.toLowerCase().includes('firefox') ? 'firefox' : 'chromium'
    return { type, path: envPath }
  }

  const detected = getDefaultExecutablePath()
  if (!detected) return null
  return {
    type: detected.toLowerCase().includes('firefox') ? 'firefox' : 'chromium',
    path: detected,
  }
}

const browser = findBrowser()
if (!browser) {
  console.error('No system browser found! Install Google Chrome, Brave, Chromium, or Firefox.')
  process.exit(1)
}

const profileDir = process.env.CHATGPT_PROXY_BROWSER_USER_DATA_DIR || getDefaultUserDataDir()
const profileDirectory = process.env.CHATGPT_PROXY_BROWSER_PROFILE_DIRECTORY || 'Default'

console.log(`Using system ${browser.type}: ${browser.path}`)
console.log(`User data dir: ${profileDir}`)
if (browser.type === 'chromium') {
  console.log(`Profile directory: ${profileDirectory}`)
}
console.log('')
console.log('  1. Log in to ChatGPT in the browser window')
console.log('  2. Once you see the chat UI, close the browser window manually')
console.log('  3. Your session will be reused by the proxy')
console.log('')

const args = browser.type === 'chromium'
  ? [
      `--user-data-dir=${profileDir}`,
      `--profile-directory=${profileDirectory}`,
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

child.on('close', () => {
  console.log(`\nBrowser closed. You can now run: make start-proxy`)
})

