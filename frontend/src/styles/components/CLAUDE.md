# src/styles/components（组件样式，给 agent）

- 每个文件对应原 styles.css 的一个连续段，文件名表示页面或组件。
- 新增组件可新建文件，但需在 `../index.css` 中按合适的级联位置 @import。
- 不要在组件文件中写 `:root` 变量定义（请放 `../themes.css`）。
- 对应 legacy 行号可在 `legacy/styles.css` 中按段标题查找（如 `/* 行情页面 */`）。
