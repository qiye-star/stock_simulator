# src/state

极简状态容器，无依赖。

```js
import { appStore } from './store.js';
const off = appStore.subscribe((state, prev) => render(state));
appStore.set({ currentSaveId: id });
```

- `createStore(initial)`：创建独立 store（功能模块可用于自身局部状态）。
- `appStore`：应用级共享状态。

## session.js
会话状态（用户、当前存档、屏幕、主页面、存档列表版本）与屏幕 / 页面切换（移植自 legacy `showScreen` / `switchTab`）。功能模块通过 `session.subscribe` 监听变化。
