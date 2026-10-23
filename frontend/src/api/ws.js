/**
 * 带自动重连的 WebSocket 客户端。
 *
 * 端点：/api/v1/ws/saves/{id}，服务端推送 {"t":"tick",...} 等 JSON 消息。
 * 重连：指数退避（minDelay * 2^n，上限 maxDelay），成功 open 后退避归零。
 * 调用 close() 后不再重连。
 */

/** @typedef {'connecting' | 'open' | 'reconnecting' | 'closed'} WsStatus */

/**
 * @typedef {Object} WsOptions
 * @property {(msg: any) => void} [onMessage] 已解析的 JSON 消息
 * @property {(status: WsStatus) => void} [onStatus]
 * @property {number} [minDelay=500]
 * @property {number} [maxDelay=10000]
 * @property {typeof WebSocket} [WebSocketImpl] 测试注入
 * @property {Location} [location] 测试注入
 */

/**
 * 由 path 构造 ws(s) URL。
 * @param {string} path 如 "/api/v1/ws/saves/1"
 * @param {Location} [loc=globalThis.location]
 * @returns {string}
 */
export function buildWsUrl(path, loc = globalThis.location) {
  const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${loc.host}${path}`;
}

/**
 * @param {string} saveId
 * @param {WsOptions} [opts]
 */
export function createSaveSocket(saveId, opts = {}) {
  return createReconnectingSocket(`/api/v1/ws/saves/${encodeURIComponent(saveId)}`, opts);
}

/**
 * @param {string} path
 * @param {WsOptions} [opts]
 */
export function createReconnectingSocket(path, opts = {}) {
  const {
    onMessage = () => {},
    onStatus = () => {},
    minDelay = 500,
    maxDelay = 10000,
    WebSocketImpl = globalThis.WebSocket,
    location = globalThis.location,
  } = opts;

  let ws = null;
  let attempt = 0;
  let timer = 0;
  let closedByUser = false;
  /** @type {WsStatus} */
  let status = 'closed';

  /** @param {WsStatus} next */
  const setStatus = (next) => {
    status = next;
    onStatus(next);
  };

  const connect = () => {
    setStatus(attempt === 0 ? 'connecting' : 'reconnecting');
    ws = new WebSocketImpl(buildWsUrl(path, location));
    ws.onopen = () => {
      attempt = 0;
      setStatus('open');
    };
    ws.onmessage = (ev) => {
      let data;
      try {
        data = JSON.parse(String(ev.data));
      } catch {
        return;
      }
      onMessage(data);
    };
    ws.onclose = () => {
      ws = null;
      if (closedByUser) {
        setStatus('closed');
        return;
      }
      const delay = Math.min(maxDelay, minDelay * 2 ** attempt);
      attempt++;
      setStatus('reconnecting');
      timer = setTimeout(connect, delay);
    };
  };

  connect();

  return {
    /** @returns {WsStatus} */
    get status() {
      return status;
    },
    /** @param {unknown} payload 以 JSON 发送 */
    send(payload) {
      if (ws && ws.readyState === 1) ws.send(JSON.stringify(payload));
    },
    close() {
      closedByUser = true;
      clearTimeout(timer);
      if (ws) ws.close();
      else setStatus('closed');
    },
  };
}
