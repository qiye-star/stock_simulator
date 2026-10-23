# 旧版存档导入模块（legacy-import）

把原版（纯前端 localStorage）的账号与存档一键导入到当前服务端账号。

## 快速开始
1. 在旧版浏览器数据所在的浏览器中登录新版账号。
2. 进入存档选择页，点击横幅「一键导入」；或在个人页点击「导入存档」选择导出的 .txt 文件。

## 目录
| 文件 | 说明 |
| --- | --- |
| `index.js` | `mount(ctx)` |
| `controller.js` | 上传与横幅逻辑 |
| `view.js` | 横幅模板 |
| `detect.js` | 纯函数：检测、标记、校验 |
| `detect.test.js` | 单元测试 |

## 对外接口
- `uploadLegacy(content, doc)`：上传旧版文本，返回是否成功。
