/**
 * 旧版存档导入（移植自 legacy/game.js importSave 4851-4935 的上传部分）。
 *
 * - 自动横幅：已登录、存在 localStorage["stock_simulator_users"] 时，在存档选择页提示一键上传。
 * - 文件导入：个人页「导入存档」按钮选择 .txt 文件后上传。
 * 服务端 POST /import/legacy 校验 XOR 文本并把存档挂到当前用户（忽略旧密码）。
 */
import * as api from '../../api/endpoints.js';
import { i18n } from '../../i18n/i18n.js';
import { errorMessage } from '../../i18n/errors.js';
import { SCREENS, bumpSaves, session } from '../../state/session.js';
import { showNotification } from '../../ui/notify.js';
import { delegate, on, setHtml } from '../../ui/dom.js';
import {
  isImportDone,
  markImportDone,
  readLegacyContent,
  shouldOfferBanner,
  validateImportFile,
} from './detect.js';
import { BANNER_ID, renderBanner } from './view.js';


/** 本页面加载周期内用户关闭过横幅。 */
let dismissed = false;
let uploading = false;

/**
 * 上传旧版文本。成功后标记完成、刷新存档列表。
 * @param {string} content
 * @param {Document} doc
 * @returns {Promise<boolean>}
 */
export async function uploadLegacy(content, doc = document) {
  if (uploading) return false;
  uploading = true;
  renderOffer(doc);
  let ok = false;
  try {
    await api.importLegacy({ content });
    ok = true;
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
  } finally {
    uploading = false;
  }
  if (ok) {
    const user = session.get().user;
    if (user) markImportDone(globalThis.localStorage, user.id);
    showNotification(i18n.t('notification.importSuccess'), 'success');
    bumpSaves();
  }
  renderOffer(doc);
  return ok;
}

/** @param {Document} doc */
function renderOffer(doc) {
  const container = doc.querySelector('#save-select-screen .save-container');
  const user = session.get().user;
  const content = readLegacyContent(globalThis.localStorage);
  const done = user ? isImportDone(globalThis.localStorage, user.id) : false;
  const show = shouldOfferBanner({ user, content, done, dismissed });

  const existing = doc.getElementById(BANNER_ID);
  if (!show || !container) {
    existing?.remove();
    return;
  }
  const t = (/** @type {string} */ k) => i18n.t(k);
  const wrap = doc.createElement('div');
  setHtml(wrap, renderBanner(t, { uploading }));
  const next = wrap.firstElementChild;
  if (existing) existing.replaceWith(next);
  else container.insertBefore(next, doc.getElementById('save-list'));
}

/** 文件选择导入（个人页按钮）。 */
function pickFile(doc) {
  const input = doc.createElement('input');
  input.type = 'file';
  input.accept = '.txt';
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    const sizeErr = validateImportFile(file);
    if (sizeErr) {
      showNotification(i18n.t(sizeErr), 'error');
      return;
    }
    let text = '';
    try {
      text = await file.text();
    } catch {
      showNotification(i18n.t('notification.importFailed'), 'error');
      return;
    }
    if (!text.trim()) {
      showNotification(i18n.t('notification.importFailed'), 'error');
      return;
    }
    await uploadLegacy(text, doc);
  });
  input.click();
}

/**
 * 绑定横幅与文件导入按钮，并在存档选择页显示横幅。返回解绑函数。
 * @param {Document} [doc=document]
 * @returns {() => void}
 */
export function initLegacyImportController(doc = document) {
  const offs = [];
  const importBtn = doc.getElementById('import-save-btn');
  if (importBtn) offs.push(on(importBtn, 'click', () => pickFile(doc)));

  // 横幅位于 #save-select-screen 内，委托事件到容器（横幅可能被重绘）
  const screen = doc.getElementById(SCREENS.SAVE_SELECT);
  if (screen) {
    offs.push(
      delegate(screen, 'click', `#${BANNER_ID} [data-action]`, (_e, el) => {
        const action = /** @type {HTMLElement} */ (el).dataset.action;
        if (action === 'dismiss') {
          dismissed = true;
          renderOffer(doc);
        } else if (action === 'upload') {
          const content = readLegacyContent(globalThis.localStorage);
          if (content) uploadLegacy(content, doc);
        }
      }),
    );
  }

  let prev = session.get();
  offs.push(
    session.subscribe((s) => {
      if (s.screen !== prev.screen || s.user !== prev.user) renderOffer(doc);
      prev = s;
    }),
  );

  // 模块可能晚于会话恢复挂载：立即按当前状态决定是否显示横幅
  renderOffer(doc);

  return () => {
    for (const off of offs) off();
  };
}
