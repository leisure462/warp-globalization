# Warp Globalization

Warp 汉化版自动化工程。仓库不保存 Warp 源码，而是在 GitHub Actions 中拉取 [warpdotdev/warp](https://github.com/warpdotdev/warp)，提取 Rust UI 字符串，使用 OpenAI 兼容接口翻译为简体中文，然后把翻译应用到源码并构建 OSS 版本。

## 使用方式

1. 在仓库 `Settings -> Secrets and variables -> Actions` 中添加：
   - `AI_API_KEY`：必填，OpenAI 或兼容服务密钥
   - `AI_BASE_URL`：可选，默认 `https://api.openai.com/v1`
   - `AI_MODEL`：可选，默认 `gpt-4o-mini`
2. 运行 `01 Translate` 工作流：
   - `upstream_ref` 默认 `main`，也可以填写 Warp 的 tag/commit/branch
   - `target_lang` 默认 `zh-CN`
   - 勾选 `chain_build` 可在翻译完成后自动触发构建
3. 运行 `02 Build` 工作流：
   - 默认构建 `windows-x86_64`
   - 产物会上传为 Actions Artifact
   - 勾选 `publish_release` 会创建 GitHub Release

翻译结果会提交到仓库的 `i18n` 分支，主分支只保存工具链和 Actions 配置。

## 本地命令

本地不需要编译 Warp，只在需要调试工具链时使用：

```bash
pip install ".[ai]"
git clone https://github.com/warpdotdev/warp.git warp
warpl10n extract --source-root warp --scan-mode heuristic
warpl10n translate --input string.json --output i18n/zh-CN.json --context string_context.json
warpl10n replace --input i18n/zh-CN.json --source-root warp --do-not-translate config/do_not_translate.json
```

## 工作流

- `01 Translate`：拉取 Warp、扫描候选 Rust 文件、提取字符串、AI 翻译、校验占位符、推送到 `i18n` 分支。
- `02 Build`：拉取 Warp、从 `i18n` 分支选择翻译文件、应用源码替换、生成补丁、在 GitHub runner 上构建。

## 当前策略

Warp 当前没有完整资源化的 i18n 文件，因此本工程采用与 zed-globalization 类似的“外部工具链 + 源码字符串替换 + CI 构建”方案。替换阶段会跳过字节字符串、raw 字符串、属性宏、纯标识符、URL、路径、MIME 类型和占位符不匹配的条目，降低破坏 Rust 语法和运行时协议字符串的风险。

## 许可证

本工具链使用 MIT License。Warp 上游源码遵循其自身许可证。

