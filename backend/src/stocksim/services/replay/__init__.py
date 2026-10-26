"""真实复盘服务（模式 E，05 §5.3）。

子模块：pack（关卡包模型与校验）、levels（导入、列表、缓存）、state（关卡包 → 行情状态）、
views（个股详情与分时）、sessions（建会话、推进、结算）、feed（事件流与 A 的适配点）、
predictions（作答与计分）、reveal（揭示）、cli（手动导入）。
由 services/market.py 在函数开头延迟导入，本包不被顶层导入。
"""
