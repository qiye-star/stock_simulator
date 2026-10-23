/**
 * REST 请求封装（fetch）。
 *
 * - 基址 /api/v1；credentials: 'same-origin'（Cookie 会话 session，httpOnly）
 * - 非 2xx 时解析错误体 {code, params}，抛出 ApiError
 * - 网络失败抛出 ApiError(code = NETWORK)
 */
import { ClientErrorCode } from '../i18n/errors.js';

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  /**
   * @param {string} code 业务错误码（ErrorCode）或 ClientErrorCode
   * @param {number} status HTTP 状态码（网络错误为 0）
   * @param {Record<string, unknown>} [params]
   */
  constructor(code, status, params = {}) {
    super(code);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.params = params;
  }
}

/**
 * @typedef {Object} RequestOptions
 * @property {Record<string, string | number | boolean | null | undefined>} [query]
 * @property {unknown} [body] 将以 JSON 发送
 * @property {AbortSignal} [signal]
 * @property {Record<string, string>} [headers]
 */

/**
 * @param {string} path 以 / 开头，相对 API_BASE，如 "/saves"
 * @param {Record<string, string | number | boolean | null | undefined>} [query]
 * @returns {string}
 */
export function buildUrl(path, query) {
  const url = new URL(API_BASE + path, globalThis.location?.origin ?? 'http://localhost');
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

/**
 * @template T
 * @param {'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'} method
 * @param {string} path
 * @param {RequestOptions} [opts]
 * @returns {Promise<T>} 成功时返回 JSON（204 返回 null）
 */
export async function request(method, path, opts = {}) {
  const headers = { Accept: 'application/json', ...(opts.headers ?? {}) };
  /** @type {RequestInit} */
  const init = { method, headers, credentials: 'same-origin', signal: opts.signal };
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }

  let res;
  try {
    res = await fetch(buildUrl(path, opts.query), init);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(ClientErrorCode.NETWORK, 0);
  }

  if (res.status === 204) return /** @type {T} */ (null);

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const code = typeof data?.code === 'string' ? data.code : ClientErrorCode.UNKNOWN;
    const params = data?.params && typeof data.params === 'object' ? data.params : {};
    throw new ApiError(code, res.status, params);
  }
  return /** @type {T} */ (data);
}

/** @template T @param {string} path @param {RequestOptions} [o] */
export const get = (path, o) => request('GET', path, o);
/** @template T @param {string} path @param {RequestOptions} [o] */
export const post = (path, o) => request('POST', path, o);
/** @template T @param {string} path @param {RequestOptions} [o] */
export const put = (path, o) => request('PUT', path, o);
/** @template T @param {string} path @param {RequestOptions} [o] */
export const patch = (path, o) => request('PATCH', path, o);
/** @template T @param {string} path @param {RequestOptions} [o] */
export const del = (path, o) => request('DELETE', path, o);
