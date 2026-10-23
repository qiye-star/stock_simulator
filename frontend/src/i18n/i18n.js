/**
 * 国际化（i18n）核心模块（ES 模块版，移植自 legacy/i18n.js）
 *
 * - t(key, params)：翻译，支持 {placeholder} 插值；缺失时回退 zh-CN，仍缺失则返回 key
 * - setLanguage(lang)：切换语言，持久化到 localStorage，刷新 DOM 并触发 onChange 回调
 * - applyToDOM(root)：批量刷新 data-i18n* 节点（见下方约定）
 *
 * DOM 约定：
 *   data-i18n="key"             -> textContent
 *   data-i18n-placeholder="key" -> placeholder
 *   data-i18n-title="key"       -> title
 *   data-i18n-html="key"        -> innerHTML（仅限静态译文，不得用于用户数据）
 *
 * @typedef {'zh-CN' | 'en-US'} Lang
 */
import zhCN from './locales/zh-CN.js';
import enUS from './locales/en-US.js';

export const STORAGE_KEY = 'stock_simulator_lang';
export const DEFAULT_LANG = 'zh-CN';

/** @type {Record<Lang, Record<string, string>>} */
const MESSAGES = { 'zh-CN': zhCN, 'en-US': enUS };

/**
 * @param {unknown} lang
 * @returns {lang is Lang}
 */
export function isSupportedLang(lang) {
  return typeof lang === 'string' && Object.prototype.hasOwnProperty.call(MESSAGES, lang);
}

export class I18n {
  /**
   * @param {Record<string, Record<string, string>>} [messages]
   * @param {{ storage?: Storage | null, doc?: Document | null }} [env] 便于测试注入
   */
  constructor(messages = MESSAGES, env = {}) {
    this.messages = messages;
    this.storage = env.storage !== undefined ? env.storage : safeLocalStorage();
    this.doc = env.doc !== undefined ? env.doc : (typeof document !== 'undefined' ? document : null);
    /** @type {Lang} */
    this.lang = DEFAULT_LANG;
    /** @type {Set<(lang: Lang, prev: Lang) => void>} */
    this.listeners = new Set();
  }

  /** 读取 localStorage 中的语言偏好并应用（无偏好时使用默认语言，不触发回调）。 */
  init() {
    let saved = null;
    try {
      saved = this.storage ? this.storage.getItem(STORAGE_KEY) : null;
    } catch {
      saved = null;
    }
    this.#apply(isSupportedLang(saved) ? saved : DEFAULT_LANG, false);
  }

  /** @returns {Lang} */
  getLanguage() {
    return this.lang;
  }

  isChinese() {
    return this.lang === 'zh-CN';
  }

  /**
   * @param {string} key
   * @param {Record<string, string | number> | null} [params]
   * @returns {string}
   */
  t(key, params = null) {
    let text = this.messages[this.lang]?.[key];
    if (text === undefined) text = this.messages[DEFAULT_LANG]?.[key];
    if (text === undefined) {
      console.warn(`[I18n] Missing translation: ${key}`);
      return key;
    }
    if (params) {
      text = text.replace(/\{(\w+)\}/g, (match, name) =>
        params[name] !== undefined ? String(params[name]) : match,
      );
    }
    return text;
  }

  /**
   * @param {Lang} lang
   * @param {{ applyDOM?: boolean, persist?: boolean }} [opts]
   */
  setLanguage(lang, opts = {}) {
    const { applyDOM = true, persist = true } = opts;
    if (!isSupportedLang(lang)) {
      console.warn(`[I18n] Unsupported language: ${lang}`);
      return;
    }
    if (lang === this.lang) return;
    const prev = this.lang;
    this.#apply(lang, persist);
    if (applyDOM) this.applyToDOM();
    for (const cb of [...this.listeners]) {
      try {
        cb(lang, prev);
      } catch (err) {
        console.error('[I18n] language change listener failed:', err);
      }
    }
  }

  toggleLanguage() {
    this.setLanguage(this.lang === 'zh-CN' ? 'en-US' : 'zh-CN');
  }

  /**
   * @param {(lang: Lang, prev: Lang) => void} cb
   * @returns {() => void} 取消订阅
   */
  onChange(cb) {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  /** @param {ParentNode} [root] 默认整个 document */
  applyToDOM(root = this.doc) {
    if (!root) return;
    root.querySelectorAll('[data-i18n]').forEach((el) => {
      el.textContent = this.t(el.getAttribute('data-i18n'));
    });
    root.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
      el.setAttribute('placeholder', this.t(el.getAttribute('data-i18n-placeholder')));
    });
    root.querySelectorAll('[data-i18n-title]').forEach((el) => {
      el.setAttribute('title', this.t(el.getAttribute('data-i18n-title')));
    });
    root.querySelectorAll('[data-i18n-html]').forEach((el) => {
      // 静态译文（来自 locales/，受控），允许 HTML；禁止传入用户数据。
      el.innerHTML = this.t(el.getAttribute('data-i18n-html'));
    });
  }

  /**
   * @param {Lang} lang
   * @param {boolean} persist
   */
  #apply(lang, persist) {
    this.lang = lang;
    if (persist && this.storage) {
      try {
        this.storage.setItem(STORAGE_KEY, lang);
      } catch {
        /* 隐私模式等场景可能不可写，忽略 */
      }
    }
    if (this.doc?.documentElement) this.doc.documentElement.lang = lang;
  }
}

function safeLocalStorage() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch {
    return null;
  }
}

/** 应用级单例。 */
export const i18n = new I18n();

/** 便捷导出：t('key', params) */
export const t = (key, params) => i18n.t(key, params);
