/**
 * 自选增删：乐观更新 marketStore.watchlist，失败回滚并提示。
 * 接口：PUT /saves/{id}/watchlist/{code}（加入）、DELETE（移除）。
 */
import { addWatchlistItem, removeWatchlistItem } from '../../api/endpoints.js';
import { marketStore } from '../market/store.js';
import { notifyError, notifyKey } from '../market/notify.js';
import { toggleWatch } from './model.js';

/** @type {Set<string>} 正在请求中的代码（防止同一只股票重复点击造成竞态） */
const pending = new Set();

/**
 * @param {string} code
 * @returns {Promise<void>}
 */
export async function toggleWatchlist(code) {
  const st = marketStore.get();
  const id = st.saveId;
  if (!id || !code) return;
  if (pending.has(code)) return;

  const prevList = st.watchlist;
  const { next, added } = toggleWatch(prevList, code);
  marketStore.set({ watchlist: next });
  pending.add(code);
  try {
    if (added) await addWatchlistItem(id, code);
    else await removeWatchlistItem(id, code);
    if (marketStore.get().saveId === id) {
      notifyKey(added ? 'notification.watchlistAdded' : 'notification.watchlistRemoved', 'success');
    }
  } catch (err) {
    if (marketStore.get().saveId === id) {
      // 回滚：仅当当前列表仍是我们乐观写入的版本时才恢复
      if (marketStore.get().watchlist === next) marketStore.set({ watchlist: prevList });
      notifyError(err);
    }
  } finally {
    pending.delete(code);
  }
}
