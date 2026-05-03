import os from 'node:os'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = path.resolve(__dirname, '..')

export function getDefaultExecutablePath() {
  if (process.platform === 'darwin') {
    for (const candidate of [
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
      '/Applications/Firefox.app/Contents/MacOS/firefox',
    ]) {
      if (fs.existsSync(candidate)) return candidate
    }
    return ''
  }

  if (process.platform === 'win32') {
    return ''
  }

  for (const candidate of ['google-chrome', 'google-chrome-stable', 'chromium-browser', 'chromium', 'firefox']) {
    const resolved = process.env.PATH
      ?.split(path.delimiter)
      .map((dir) => path.join(dir, candidate))
      .find((fullPath) => fs.existsSync(fullPath))
    if (resolved) return resolved
  }

  return ''
}

export function getDefaultUserDataDir() {
  const executable = (getDefaultExecutablePath() || '').toLowerCase()
  const home = os.homedir()

  if (process.platform === 'darwin') {
    if (executable.includes('brave')) return path.join(home, 'Library', 'Application Support', 'BraveSoftware', 'Brave-Browser')
    if (executable.includes('chrome')) return path.join(home, 'Library', 'Application Support', 'Google', 'Chrome')
    if (executable.includes('chromium')) return path.join(home, 'Library', 'Application Support', 'Chromium')
    if (executable.includes('firefox')) return path.join(home, 'Library', 'Application Support', 'Firefox')
  } else if (process.platform === 'win32') {
    if (executable.includes('brave')) return path.join(home, 'AppData', 'Local', 'BraveSoftware', 'Brave-Browser', 'User Data')
    if (executable.includes('chrome')) return path.join(home, 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
    if (executable.includes('chromium')) return path.join(home, 'AppData', 'Local', 'Chromium', 'User Data')
    if (executable.includes('firefox')) return path.join(home, 'AppData', 'Roaming', 'Mozilla', 'Firefox')
  } else {
    if (executable.includes('brave')) return path.join(home, '.config', 'BraveSoftware', 'Brave-Browser')
    if (executable.includes('chrome')) return path.join(home, '.config', 'google-chrome')
    if (executable.includes('chromium')) return path.join(home, '.config', 'chromium')
    if (executable.includes('firefox')) return path.join(home, '.mozilla', 'firefox')
  }

  return path.join(projectRoot, 'data', 'browser_profile')
}
