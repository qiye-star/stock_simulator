# 新手引导模块（tutorial）

首次进入主界面时的 9 步引导浮层，可跳过；完成后记录到账号。

## 快速开始
用一个 `tutorial_completed=false` 的账号登录并进入存档即可看到。

## 目录
| 文件 | 说明 |
| --- | --- |
| `index.js` | `mount(ctx)` |
| `controller.js` | 流程：开始、下一步、结束、持久化 |
| `view.js` | 浮层渲染 |
| `steps.js` | 步骤表与位置计算（纯函数） |
| `steps.test.js` | 单元测试 |

## 对外接口
- `startTutorial(doc)`、`nextStep(doc)`、`end(doc)`。
