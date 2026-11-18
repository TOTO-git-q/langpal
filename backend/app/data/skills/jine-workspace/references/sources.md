# 阅读来源

- 论文用 `/reader/papers`，阅读素材用 `/reader/news`。`inspect.sources` 列出当前可用的来源（id、名称、类型、语言、是否启用）。
- 内置来源（BBC、NASA、ITmedia、経済産業省、Wikipedia、BCcampus 教材、Europe PMC、Crossref、arXiv、DataCite、HAL）和用户自定义来源（JSON 字段映射或 RSS/Atom）在同一张列表里，可启停（排序只在设置页）。新增或修改自定义来源用 `source.save`（内置、私网和带密钥的来源不能改，只能启停），启停用 `source.enable`。`source.test` 是只读的：在回复里给出要测的来源 `test_source_id`，由用户点按钮试连，管家自己不发请求。密钥只能由用户在设置页填写；「允许私有网络」只能由用户在本机设置页打开，管家不能改。用户要换默认来源时，用 `reading.defaults` 选 `inspect.sources` 里已启用且语言匹配的 id（或 `all`）。
- 可参考 [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)、[Europe PMC REST API](https://europepmc.org/RestfulWebService)、[arXiv API](https://info.arxiv.org/help/api/user-manual.html)、[DataCite REST API](https://support.datacite.org/docs/api)、[HAL API](https://api.archives-ouvertes.fr/docs/)。开放全文、摘要、来源链接各自说明。原始发布方的权限与归属由来源保留。
- 仓库变更入口为 `backend/app/services/reading_sources.py`、`backend/app/routers/reading.py`、`frontend/js/settings-reading.js` 和 `frontend/js/reading.js`。
