/**
 * 旧版（legacy）本地数据检测与校验的纯函数。
 * 旧版把全部用户以 Crypto.encrypt(JSON) 的文本写入 localStorage["stock_simulator_users"]，
 * 与导出文件同格式，可直接作为 POST /import/legacy 的 content。
 */

export const LEGACY_USERS_KEY = 'stock_simulator_users';
export const LEGACY_DONE_KEY_PREFIX = 'stock_simulator_legacy_import_done:';
/** 与 legacy 导入上限一致：5MB。 */
export const MAX_IMPORT_BYTES = 5 * 1024 * 1024;

/**
 * @param {Pick<Storage, 'getItem'> | null | undefined} storage
 * @returns {string | null} 旧版数据文本；不存在或为空返回 null
 */
export function readLegacyContent(storage) {
  if (!storage) return null;
  try {
    const raw = storage.getItem(LEGACY_USERS_KEY);
    return typeof raw === 'string' && raw.trim() ? raw : null;
  } catch {
    return null;
  }
}

/**
 * 当前用户是否已标记导入（本浏览器内，仅作为横幅显示的便利项）。
 * @param {Pick<Storage, 'getItem'> | null | undefined} storage
 * @param {string} userId
 */
export function isImportDone(storage, userId) {
  if (!storage || !userId) return false;
  try {
    return storage.getItem(LEGACY_DONE_KEY_PREFIX + userId) === '1';
  } catch {
    return false;
  }
}

/**
 * @param {Pick<Storage, 'setItem'> | null | undefined} storage
 * @param {string} userId
 */
export function markImportDone(storage, userId) {
  if (!storage || !userId) return;
  try {
    storage.setItem(LEGACY_DONE_KEY_PREFIX + userId, '1');
  } catch {
    /* 忽略 */
  }
}

/**
 * 文件大小校验。
 * @param {{ size: number }} file
 * @returns {string | null} i18n key：超限返回 notification.importTooLarge，否则 null
 */
export function validateImportFile(file) {
  if (!Number.isFinite(file.size) || file.size < 0) return 'notification.importFailed';
  if (file.size > MAX_IMPORT_BYTES) return 'notification.importTooLarge';
  return null;
}

/**
 * 是否应显示「发现旧版数据」横幅。
 * @param {{ user: { id: string } | null, content: string | null, done: boolean, dismissed: boolean }} input
 */
export function shouldOfferBanner({ user, content, done, dismissed }) {
  return Boolean(user) && Boolean(content) && !done && !dismissed;
}
