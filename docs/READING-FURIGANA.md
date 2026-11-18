# 日语注音

## API

`POST /api/reader/furigana`（同源），输入 `{text: string}`（最多 12000 字符），返回 `{tokens: [{text, reading, parts: [{text, reading}]}]}`。所有 token 的 text 拼起来严格等于输入；parts 也能还原该 token。

用本机的 SudachiPy / sudachidict_core，不调语言模型，不向外发送文章。读音取 `reading_form()`，片假名转平假名；词尾假名能和读音对齐时放在 ruby 外。词典不认识的词、没有汉字的词、读音不可靠的词不注音。多音词受词典和分词能力限制，不是完整的语义消歧或人名校对。

参考：[SudachiPy](https://github.com/WorksApplications/sudachi.rs/tree/develop/python)、[HTML ruby](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/ruby)。

## 前端

`LP.furigana`（`frontend/js/furigana.js`）提供 `enabled / setEnabled / decorate / clear / sourceText / rangeText / range`。开关存在浏览器键 `jine.reader.furigana`，跨窗口同步，`window` 上发 `lp:furigana` 事件 `{enabled}`。

注音不写回原文。选段、查词、批注索引和复制都去掉 `rt/rp`；`range(root,start,length)` 用原文的 UTF-16 偏移，兼容已有批注锚点。日语 PDF 开注音时显示该页提取的文字，关掉恢复原 PDF；扫描件没有文本层时不自动 OCR。聊天可直接用 token.reading 生成 ruby。

## 测试

`tests/test_furigana.py`（真实词典）、`tests/test_furigana_reader_ui.mjs`（完整阅读器）。
