/**
 * 跨功能窗口事件名（唯一定义处）。全部派发到 window，监听方用 window.addEventListener。
 *
 * - SELECT_STOCK_EVENT：选股意图，detail { code: string, target: 'trade' | 'auto-trade' | 'market' }。
 *   持仓右键菜单派发；market 选中该股票并刷新详情，trade 填入代码，auto-trade 填入配置表单代码。
 * - ORDER_EVENT：下单成功，detail { saveId: string, code: string, side: 'buy' | 'sell' }。
 *   trade 派发；portfolio 据此刷新持仓与成交。
 */
export const SELECT_STOCK_EVENT = 'stocksim:select-stock';
export const ORDER_EVENT = 'stocksim:order';
