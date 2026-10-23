/**
 * 旧版数据横幅（插入到存档选择页的 .save-container 中，#legacy-import-banner）。
 */
import { html } from '../../ui/html.js';

export const BANNER_ID = 'legacy-import-banner';

/**
 * @param {(key: string) => string} t
 * @param {{ uploading: boolean }} state
 */
export function renderBanner(t, { uploading }) {
  return html`<div id="${BANNER_ID}" class="legacy-import-banner" role="status">
    <p>${t('legacyImport.found')}</p>
    <div class="legacy-import-actions">
      <button type="button" class="btn-primary btn-small" data-action="upload" ${uploading ? 'disabled' : ''}>${t('legacyImport.upload')}</button>
      <button type="button" class="btn-text" data-action="dismiss">${t('legacyImport.dismiss')}</button>
    </div>
  </div>`;
}
