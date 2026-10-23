/**
 * 应用入口：样式 -> i18n -> 主题 -> 通用 UI -> 功能模块。
 */
import './styles/index.css';
import { i18n } from './i18n/i18n.js';
import { appStore } from './state/store.js';
import { applyTheme } from './ui/theme.js';
import { initNumberStepper } from './ui/numberStepper.js';
import { mountFeatures } from './features/index.js';

function bootstrap() {
  // 1. 语言：读取偏好并刷新静态文案
  i18n.init();
  i18n.applyToDOM();
  i18n.onChange((lang) => appStore.set({ lang }));
  appStore.set({ lang: i18n.getLanguage() });

  // 2. 主题：默认深色，之后由 /me 或本地偏好覆盖
  applyTheme(appStore.get().theme);
  appStore.subscribe((state, prev) => {
    if (state.theme !== prev.theme) applyTheme(state.theme);
  });

  // 3. 通用 UI：数字输入框步进按钮
  initNumberStepper(document);

  // 4. 功能模块（见 features/index.js）
  mountFeatures({ store: appStore, i18n, doc: document });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
