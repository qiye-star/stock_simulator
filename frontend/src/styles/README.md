# src/styles

应用样式，由原版 `legacy/styles.css` 按功能段切分而来。

- `index.css`：唯一入口，按原顺序导入以保持级联一致。
- `base.css`：全局重置、body、#app。
- `themes.css`：`:root` 颜色变量、浅色（`light-theme`）与节日（`festival-theme`）主题。
- `components/`：认证、通用按钮与通知、存档、开局设置、主界面、行情、交易、持仓、个人主页、弹窗、时间控制、成就弹窗、新手引导、滚动条、自动交易、表单控件、数字步进、右键菜单等。
- `responsive*.css`：原文件中的媒体查询段。

修改样式时注意 @import 顺序即优先级顺序。
