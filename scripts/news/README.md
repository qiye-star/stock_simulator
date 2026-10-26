# scripts/news

事件快讯文案的离线生成流水线。

| 文件 | 作用 |
|---|---|
| `fetch_akshare_titles.py` | 手动抓取真实标题语料（需 akshare），输出到 `corpus/`（不提交） |
| `extract_patterns.py` | 语料 → 句式候选（槽位化、聚类、猜 subtype） |
| `templates_src.json` | 人工整理的句式源（提交，只含句式） |
| `build_templates.py` | 校验 + 生成 `backend/src/stocksim/data/news_templates.json` |

```bash
python3 scripts/news/build_templates.py          # 生成
python3 scripts/news/build_templates.py --check  # 只校验，产物过期会报错
```

模板格式与约束见 `docs/10.26-plan/01-事件行情.md` §7.4。
