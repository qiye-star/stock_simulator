import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, buildUrl, request } from './http.js';

const realFetch = globalThis.fetch;

function mockFetch(impl) {
  globalThis.fetch = vi.fn(impl);
  return globalThis.fetch;
}

function jsonResponse(status, body) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  globalThis.fetch = realFetch;
});

describe('buildUrl', () => {
  it('prefixes /api/v1 and skips empty query values', () => {
    expect(buildUrl('/saves')).toBe('/api/v1/saves');
    expect(buildUrl('/saves/1/trades', { cursor: 'abc', x: undefined, y: '' })).toBe('/api/v1/saves/1/trades?cursor=abc');
  });
});

describe('request', () => {
  it('sends same-origin credentials and JSON body', async () => {
    const fetchMock = mockFetch(async () => jsonResponse(200, { ok: true }));
    const data = await request('POST', '/auth/login', { body: { username: 'u', password: 'p' } });
    expect(data).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/auth/login');
    expect(init.credentials).toBe('same-origin');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({ username: 'u', password: 'p' });
  });

  it('returns null for 204', async () => {
    mockFetch(async () => new Response(null, { status: 204 }));
    await expect(request('DELETE', '/saves/1')).resolves.toBeNull();
  });

  it('throws ApiError with code and params from the error body', async () => {
    mockFetch(async () => jsonResponse(400, { code: 'TRADE_T1_SELL_BLOCKED', params: { shares: 100 } }));
    const err = await request('POST', '/saves/1/orders').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('TRADE_T1_SELL_BLOCKED');
    expect(err.status).toBe(400);
    expect(err.params).toEqual({ shares: 100 });
  });

  it('falls back to UNKNOWN when the error body is not in contract shape', async () => {
    mockFetch(async () => new Response('<html>502</html>', { status: 502 }));
    const err = await request('GET', '/saves').catch((e) => e);
    expect(err.code).toBe('UNKNOWN');
    expect(err.status).toBe(502);
  });

  it('maps network failure to NETWORK', async () => {
    mockFetch(async () => {
      throw new TypeError('Failed to fetch');
    });
    const err = await request('GET', '/me').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('NETWORK');
    expect(err.status).toBe(0);
  });
});
