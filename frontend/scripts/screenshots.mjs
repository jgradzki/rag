// Takes the README screenshots: `make shots` (or `npm run shots` in frontend/).
//
// Starts its own backend on a temporary data dir holding only backend/sample_docs -
// never your own index or documents - plus a Vite dev server, asks one question with the
// LLM set in backend/.env and saves docs/screenshots/*.png. Needs `make setup`, a working
// LLM and a Chromium for Playwright (`make shots` installs it).
import { execFileSync, spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readdirSync, rmSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { chromium } from 'playwright'

const REPO = path.resolve(import.meta.dirname, '../..')
const BACKEND = path.join(REPO, 'backend')
const FRONTEND = path.join(REPO, 'frontend')
const SAMPLE_DOCS = path.join(BACKEND, 'sample_docs')
const OUT_DIR = path.join(REPO, 'docs/screenshots')
// 127.0.0.1, not localhost: on Windows localhost may resolve to ::1, where another
// process could answer. Ports away from the dev ones (8000 / 5173).
const HOST = '127.0.0.1'
const BACKEND_PORT = 8790
const FRONTEND_PORT = 5190
const QUESTION = 'How long did the Opportunity rover operate, and what ended its mission?'

const PYTHON = path.join(
  BACKEND,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)

// One answer, two pictures: the answer is generated once, then the page is re-laid out.
const SHOTS = [
  { name: 'chat', viewport: { width: 1280, height: 860 }, colorScheme: 'light' },
  { name: 'chat-mobile-dark', viewport: { width: 393, height: 852 }, colorScheme: 'dark' },
]

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// A busy port would make the new server exit while the old one answers our requests -
// and the screenshots would show that one's documents.
async function assertPortFree(port) {
  const server = createServer()
  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject)
      server.listen(port, HOST, resolve)
    })
  } catch {
    throw new Error(`Port ${port} is in use - stop what runs there (an earlier make shots?)`)
  } finally {
    server.close()
  }
}

function start(name, command, args, options) {
  const child = spawn(command, args, { stdio: ['ignore', 'ignore', 'inherit'], ...options })
  // Rejects when the process ends, so a crash stops the wait instead of a 10-minute timeout.
  child.exited = new Promise((_, reject) => {
    child.once('exit', (code) => reject(new Error(`${name} exited (code ${code}) - see above`)))
    child.once('error', (e) => reject(new Error(`${name} could not start: ${e.message}`)))
  })
  child.exited.catch(() => {}) // also ends during cleanup - that is not an error
  return child
}

async function waitForUrl(url, seconds, child) {
  const poll = (async () => {
    for (let i = 0; i < seconds; i++) {
      try {
        if ((await fetch(url)).ok) return
      } catch {
        // not listening yet
      }
      await sleep(1000)
    }
    throw new Error(`${url} did not answer within ${seconds} s`)
  })()
  await Promise.race([poll, child.exited])
}

let backend, frontend, browser, dataDir
let cleanedUp = false
async function cleanup() {
  if (cleanedUp) return
  cleanedUp = true
  backend?.kill()
  frontend?.kill()
  try {
    await browser?.close()
  } catch (e) {
    console.warn(`cleanup: ${e.message}`)
  }
  if (!dataDir) return
  // Chroma may still hold its files for a moment after the backend exits (Windows).
  await sleep(1500)
  try {
    rmSync(dataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 })
  } catch (e) {
    console.warn(`cleanup: could not remove ${dataDir}: ${e.message}`)
  }
}
// Ctrl+C or a closed terminal would otherwise skip `finally` and leave the servers up.
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.once(signal, async () => {
    await cleanup()
    process.exit(130)
  })
}

try {
  await assertPortFree(BACKEND_PORT)
  await assertPortFree(FRONTEND_PORT)

  // The embedding model is shared with your own instance, so it is not downloaded again.
  // PYTHONUTF8: Python on Windows would print a non-ASCII path in the ANSI code page.
  const modelsDir = execFileSync(
    PYTHON,
    ['-c', 'from app.config import get_settings; print(get_settings().models_cache_dir)'],
    { cwd: BACKEND, encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1' } },
  ).trim()
  dataDir = mkdtempSync(path.join(tmpdir(), 'rag-shots-'))
  const backendUrl = `http://${HOST}:${BACKEND_PORT}`
  const origin = `http://${HOST}:${FRONTEND_PORT}`

  backend = start(
    'backend',
    PYTHON,
    [
      '-m',
      'uvicorn',
      'app.main:create_app',
      '--factory',
      '--host',
      HOST,
      '--port',
      String(BACKEND_PORT),
    ],
    {
      cwd: BACKEND,
      env: {
        ...process.env,
        DATA_DIR: dataDir,
        MODELS_DIR: modelsDir,
        // Pinned: backend/.env may point SAMPLE_DOCS_DIR at your own documents.
        SAMPLE_DOCS_DIR: SAMPLE_DOCS,
        INDEX_SAMPLES_ON_STARTUP: 'true',
        CORS_ORIGINS: JSON.stringify([origin]),
      },
    },
  )
  frontend = start(
    'frontend',
    process.execPath,
    [
      path.join(FRONTEND, 'node_modules/vite/bin/vite.js'),
      '--host',
      HOST,
      '--port',
      String(FRONTEND_PORT),
      '--strictPort',
    ],
    { cwd: FRONTEND, env: { ...process.env, API_URL: backendUrl } },
  )

  // The first start may download the embedding model and indexes the samples.
  await waitForUrl(`${backendUrl}/api/health`, 600, backend)
  await waitForUrl(`${origin}/api/health`, 60, frontend)

  // The pictures are published: refuse to take them of anything but the sample documents.
  const samples = new Set(readdirSync(SAMPLE_DOCS))
  const indexed = (await (await fetch(`${backendUrl}/api/documents`)).json()).map((d) => d.name)
  if (!indexed.length || indexed.some((name) => !samples.has(name))) {
    throw new Error(`The index holds more than the sample documents: ${indexed.join(', ')}`)
  }

  browser = await chromium.launch()
  const page = await browser.newPage({ viewport: SHOTS[0].viewport, deviceScaleFactor: 2 })
  await page.goto(origin)
  await page.getByRole('textbox', { name: 'Question' }).fill(QUESTION)
  await page.keyboard.press('Enter')

  console.log('Waiting for the answer (the LLM set in backend/.env)...')
  await page.waitForFunction(
    () =>
      !document.querySelector('input[aria-label="Question"]')?.disabled &&
      document.querySelector('.message.assistant'),
    null,
    { timeout: 300_000 },
  )
  // Keep the committed pictures unless this answer is worth showing.
  const answer = page.locator('.message.assistant')
  const error = answer.locator('.error')
  if (await error.count()) throw new Error(`The answer failed: ${await error.textContent()}`)
  if (!(await answer.locator(':scope > :not(.muted):not(.sources)').count())) {
    throw new Error('The LLM returned an empty answer - try again or another model')
  }
  if (!(await answer.locator('.sources').count())) {
    throw new Error('No sources were retrieved - check MIN_RELEVANCE / EMBEDDING_MODEL')
  }
  await answer.locator('.sources summary').click()

  mkdirSync(OUT_DIR, { recursive: true })
  for (const shot of SHOTS) {
    await page.setViewportSize(shot.viewport)
    await page.emulateMedia({ colorScheme: shot.colorScheme })
    // Show the question and the start of the answer, not the end of the long sources list.
    await page.evaluate(() => {
      const list = document.querySelector('.messages')
      const question = document.querySelector('.message.user')
      list.scrollTop = question.offsetTop - list.offsetTop - 16
    })
    await sleep(300)
    const file = path.join(OUT_DIR, `${shot.name}.png`)
    await page.screenshot({ path: file })
    console.log(`Saved ${path.relative(REPO, file)}`)
  }
} finally {
  await cleanup()
}
