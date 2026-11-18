# 语音与复习偏好

- 文字模型、听力合成、实时对话是三条配置路径。`voice.listening` 可选 Kokoro 或已配置的兼容合成方案，可调整每语言 A/B 音色和语速。选择音色时使用 `inspect` 列出的支持项。兼容服务地址和密钥由用户在专用设置配置。
- `review.preference` 可设 `reviewKind` 为 `all`、`reading`、`listening`，或 `reviewLanguage` 为已登记语言代码，空值表示全部语言。这个操作单独提交，因为它由当前浏览器保存。
- `language.add` 只登记语言及显示名。新语种的听力题型、音色和考试规格取决于相应工具的真实支持，语言登记后不要承诺各模块已经齐备。
- `coach.preferences` 可按明确请求改用用户给出的口语服务地址、登记该服务确实支持的语言或开关口语课与聊天联动。空地址使用 JINE 的本机服务。本机服务的语种为英语和日语。
- 源文件为 `backend/app/services/listening_settings.py`、`listening_tts.py`、`frontend/js/review.js` 和 `frontend/js/state.js`。先用两句可验证的合成脚本检查语种、声线与回放，再验证错题记录能复听且不提前揭示答案。
