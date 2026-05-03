import os from 'node:os'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = path.resolve(__dirname, '..')

export function getDefaultUserDataDir() {
  return path.join(projectRoot, 'data', 'browser_profile')
}

export function getDefaultExecutablePath() {
  return ''
}
