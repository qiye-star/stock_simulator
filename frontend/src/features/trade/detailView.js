/**
 * 股票详情的报价区：名称、现价、涨跌、涨跌停、五档盘口（移植自 legacy/game.js updateStockDetail 2515-2582）。
 *
 * 拥有：#detail-name #detail-code #detail-price #detail-change #limit-up-price #limit-down-price
 *       #ask1..5-price/vol #bid1..5-price/vol
 * 图表（canvas）与按钮不在此处。价格输入框不在此处被改写（见 form.js）。
 */
import { marketStore } from '../market/store.js';
import { centsText, changeDirection, changeText } from '../market/model.js';
import { setClass, setText } from '../market/dom.js';

/**
 * @param {Document} [doc]
 * @returns {() => void}
 */
export function initDetailView(doc = document) {
  const $ = (id) => doc.getElementById(id);
  const el = {
    name: $('detail-name'),
    code: $('detail-code'),
    price: $('detail-price'),
    change: $('detail-change'),
    up: $('limit-up-price'),
    down: $('limit-down-price'),
  };
  const askPrice = [1, 2, 3, 4, 5].map((k) => $(`ask${k}-price`));
  const askVol = [1, 2, 3, 4, 5].map((k) => $(`ask${k}-vol`));
  const bidPrice = [1, 2, 3, 4, 5].map((k) => $(`bid${k}-price`));
  const bidVol = [1, 2, 3, 4, 5].map((k) => $(`bid${k}-vol`));

  /** @param {import('../market/model.js').Detail | null} d */
  function render(d) {
    if (!d) {
      setText(el.name, '--');
      setText(el.code, '--');
      setText(el.price, '--');
      setClass(el.price, 'price');
      setText(el.change, '--');
      setClass(el.change, 'change');
      setText(el.up, '--');
      setText(el.down, '--');
      for (let i = 0; i < 5; i++) {
        setText(askPrice[i], '--');
        setText(askVol[i], '--');
        setText(bidPrice[i], '--');
        setText(bidVol[i], '--');
      }
      return;
    }
    const dir = changeDirection(d.change_bp);
    setText(el.name, d.name);
    setText(el.code, d.code);
    setText(el.price, centsText(d.price_cents));
    setClass(el.price, `price ${dir}`);
    setText(el.change, changeText(d.change_bp));
    setClass(el.change, `change ${dir}`);
    setText(el.up, centsText(d.limit_up_cents));
    setText(el.down, centsText(d.limit_down_cents));
    // 卖一在中间、卖五在顶部：ask{k} 对应 asks[k-1]（asks 按由近到远排列）
    for (let i = 0; i < 5; i++) {
      const ask = d.asks[i];
      const bid = d.bids[i];
      setText(askPrice[i], ask ? centsText(ask.price_cents) : '--');
      setText(askVol[i], ask ? String(ask.volume) : '--');
      setText(bidPrice[i], bid ? centsText(bid.price_cents) : '--');
      setText(bidVol[i], bid ? String(bid.volume) : '--');
    }
  }

  render(marketStore.get().detail);
  const unsubscribe = marketStore.subscribe((s, prev) => {
    if (s.detail !== prev.detail) render(s.detail);
  });
  return unsubscribe;
}
