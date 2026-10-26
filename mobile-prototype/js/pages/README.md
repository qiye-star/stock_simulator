# js/pages

页面：行情/自选、个股详情、持仓、我的、自动交易（二级页）、玩法（hub，分区由各玩法功能注册；每日挑战由 `features/challenge` 提供）、快讯（⑤ 起由 `features/news` 提供，占位工厂保留）、登录。每个页面一个文件，由 `app.js` 注册到 hash 路由。各页面的交互说明见 `mobile-prototype/README.md`。
