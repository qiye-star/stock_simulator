# css

原型样式。`index.html` 依次引入四个文件：`tokens.css` → `base.css` → `components.css` → `pages.css`，玩法样式在其后加载（`features/*.css`，见 `features/README.md`）。

想换主题时只改 `tokens.css` 即可：强调色是 `--accent`，涨跌色是 `--up` / `--down`，背景是 `--bg-0..2`。
