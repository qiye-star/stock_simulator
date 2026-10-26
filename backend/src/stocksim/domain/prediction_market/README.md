# domain/prediction_market

预测市场（模式 D）的纯函数：LMSR 做市定价与取整、挑战回合的事件合约生成与结算判定、下单限额判定。

- 设计依据：`docs/10.26-plan/04-预测市场.md`。
- 定价：`lmsr.py`，全部 `decimal`（prec=50），买入向上取整、卖出向下取整，份额整数，每份兑付 100 积分。
- 合约：`contracts.py`，每个重大回合事件 1 个 5 档分档合约，传闻再加 1 个真假合约；档位与窗口复用 `domain/predictions`。
- 限额：`limits.py`，单市场净投入、单场挑战买入额度、份额与回款范围。
- 常量与开盘先验：`constants.py`；分档先验由 `scripts/pm_prior_report.py` 离线统计。
- 服务层（积分账本、交易事务、并发、状态迁移）不在本包；本包只给出纯函数，由 `services/` 在后续步骤调用。
