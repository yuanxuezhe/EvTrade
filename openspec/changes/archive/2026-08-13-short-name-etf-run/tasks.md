# Tasks — short_name 里 ETF 整串保留

> 根因：to_short_name 对 lazy_pinyin 每段取 s[0]，pypinyin 把 ASCII run(ETF/50ETF)
> 当一个段 → 只剩首字符(E/5)。修复：ASCII run 整串保留大写。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 主 spec REQ-STOCK-007 算法第 3 步补充 ASCII run 规则
- [x] 1.3 commit: `docs(spec): REQ-STOCK-007 ASCII run 整串保留 (ETF/50ETF 不再截断)`（30ed08b）

## 2 — 代码

- [x] 2.1 `server/services/short_name.py`：`re.split(r"([A-Za-z0-9]+)", name)` 分离；
      汉字段拼音首字母、ASCII run 整串保留大写；docstring 加 ETF 示例
- [x] 2.2 commit: `fix(backend): to_short_name ASCII run 整串保留, ETF 不再只剩 E`（c26c0dd）

## 3 — 验证

- [x] 3.1 测试用例：ETF/50ETF/纯汉字/ST 前缀回归 全绿（8 passed）
- [x] 3.2 commit: `test(backend): to_short_name ASCII run / ST 前缀 / 空输入用例`（b7b0723）
