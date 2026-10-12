import assert from 'node:assert/strict'
import test from 'node:test'
import { api, ApiError, setUnauthorizedHandler } from '../src/api.ts'

// A different saved workspace must never replace the archive's explicit scope.
globalThis.localStorage = { getItem: () => '9' }

test('archive filters preserve date, search punctuation, pagination and explicit organization', async () => {
  const originalFetch = globalThis.fetch
  let call
  globalThis.fetch = async (url, options) => {
    call = { url, options }
    return Response.json({ total: 1, dates: [], exports: [], items: [{ row_label: 'Browning' }] })
  }
  try {
    const page = await api.huntxArchive(5, {
      capture_date: '2026-10-09', query: 'Walmart & Bass Pro', limit: 20, offset: 0,
    })
    const url = new URL(call.url, 'https://faithbook.test')
    assert.equal(url.pathname, '/api/huntx/archive')
    assert.equal(url.searchParams.get('query'), 'Walmart & Bass Pro')
    assert.equal(url.searchParams.get('capture_date'), '2026-10-09')
    assert.equal(url.searchParams.get('offset'), '0')
    assert.equal(call.options.headers['X-Organization-ID'], '5')
    assert.equal(call.options.cache, 'no-store')
    assert.equal(page.items[0].row_label, 'Browning')
  } finally { globalThis.fetch = originalFetch }
})

test('image reads are authenticated and reject an HTML page returned as a successful response', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    assert.equal(new URL(url, 'https://faithbook.test').searchParams.get('thumbnail'), 'true')
    assert.equal(options.headers['X-Organization-ID'], '5')
    assert.equal(options.credentials, 'same-origin')
    return new Response('not an image', { headers: { 'Content-Type': 'text/html' } })
  }
  try {
    await assert.rejects(api.huntxFile(5, 4, true), error => error instanceof ApiError && error.status === 502)
    globalThis.fetch = async () => new Response(new Uint8Array([255, 216, 255]), {
      headers: { 'Content-Type': 'image/jpeg' },
    })
    assert.equal((await api.huntxFile(5, 4)).type, 'image/jpeg')
  } finally { globalThis.fetch = originalFetch }
})

test('file downloads support JSON metadata while expired sessions trigger the normal login handler', async () => {
  const originalFetch = globalThis.fetch
  let expired = 0
  setUnauthorizedHandler(() => { expired += 1 })
  globalThis.fetch = async url => {
    assert.equal(new URL(url, 'https://faithbook.test').searchParams.get('download'), 'true')
    return Response.json({ price: 99 })
  }
  try {
    assert.equal(await (await api.huntxDownload(5, 8)).text(), '{"price":99}')
    globalThis.fetch = async () => Response.json({ detail: 'Session expirée' }, { status: 401 })
    await assert.rejects(api.huntxFile(5, 4), error => error.status === 401 && error.message === 'Session expirée')
    assert.equal(expired, 1)
  } finally { globalThis.fetch = originalFetch; setUnauthorizedHandler(() => {}) }
})

test('leaving an archive cancels its in-flight image request without treating it as a timeout', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
  })
  try {
    const controller = new AbortController()
    const pending = api.huntxFile(5, 4, true, controller.signal)
    controller.abort()
    await assert.rejects(pending, error => error.name === 'AbortError')
    assert.throws(() => api.huntxArchive(0), /Espace de travail invalide/)
    await assert.rejects(api.huntxFile(5, -1), /Fichier HuntX invalide/)
  } finally { globalThis.fetch = originalFetch }
})
