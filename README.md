# Warp Globalization

Warp 汉化版自动化工程。仓库不保存 Warp 源码，而是在 GitHub Actions 中拉取 [warpdotdev/warp](https://github.com/warpdotdev/warp)，提取 Rust UI 字符串，使用 OpenAI 兼容接口翻译为简体中文，然后把翻译应用到源码并构建 OSS 版本。

## 使用方式

1. 在仓库 `Settings -> Secrets and variables -> Actions` 中添加：
   - `AI_API_KEY`：必填，OpenAI 或兼容服务密钥
   - `AI_BASE_URL`：可选，默认 `https://api.openai.com/v1`
   - `AI_MODEL`：可选，默认 `gpt-4o-mini`
   - `AI_RPM`：可选，默认 `60`，设为 `0` 表示不限速
   - `AI_CONCURRENCY`：可选，默认 `8`
2. 运行 `01 Translate` 工作流：
   - `upstream_ref` 默认 `latest`，会自动解析 Warp 上游最新 release；也可以填写 Warp 的 tag/commit/branch
   - `target_lang` 默认 `zh-CN`
   - 勾选 `chain_build` 后，翻译成功并推送 `i18n` 分支后会自动启动 `02 Build`
   - `publish_release` 默认开启，构建成功后会用上游 release 名称发布本仓库 Release
3. 运行 `02 Build` 工作流：
   - `upstream_ref` 默认 `latest`，会自动拉取 Warp 最新 release
   - 默认构建 `windows-x86_64`
   - 产物会上传为 Actions Artifact
   - `publish_release` 默认开启，Release tag/name 使用上游 release 名称
   - Windows 安装版会把软件内置更新检查源改为本仓库 Release，并从本仓库 Release assets 下载新版安装包

翻译结果会提交到仓库的 `i18n` 分支，主分支只保存工具链和 Actions 配置。
每次翻译都会同时维护 `i18n/<版本>/<语言>.json` 和 `i18n/<语言>.json`。后者作为跨版本翻译记忆，新 upstream commit 没有精确版本翻译时会自动复用它，只补翻新增或变更的字符串。
`01 Translate` 也会按计划定时检查 Warp 最新 release；如果本仓库已经存在同名 Release，就会跳过本次翻译和构建，避免重复发布。

## 安装版内部更新

`02 Build` 在生成源码补丁前会执行 `warpl10n patch-update`，把 Warp OSS 的 Windows 更新逻辑改为：

- 启用 OSS Windows bundle 的 `autoupdate` 与更新 UI feature
- 查询 `https://api.github.com/repos/<本仓库>/releases/latest`
- 使用最新 Release tag 和当前软件内置版本比较
- 从 `https://github.com/<本仓库>/releases/download/<tag>/warp-<语言>-windows-x86_64-setup-<tag>.exe` 下载安装包
- 复用 Warp 原有 Windows 更新安装流程执行新版安装器

这个能力只针对安装版。免安装 zip 仍然需要用户手动下载并保持 `resources\` 目录结构。

## 本地命令

本地不需要编译 Warp，只在需要调试工具链时使用：

```bash
pip install ".[ai]"
git clone https://github.com/warpdotdev/warp.git warp
warpl10n extract --source-root warp --scan-mode heuristic
warpl10n translate --input string.json --output i18n/zh-CN.json --context string_context.json
warpl10n replace --input i18n/zh-CN.json --source-root warp --do-not-translate config/do_not_translate.json
warpl10n patch-update --source-root warp --repo leisure462/warp-globalization --lang zh-CN
```

## 工作流

- `01 Translate`：解析 Warp 最新 release 或指定 ref、拉取 Warp、扫描候选 Rust 文件、提取字符串、AI 翻译、校验占位符、推送到 `i18n` 分支，并上传自动构建/发布请求。
- `02 Build`：支持手动运行，也会在 `01 Translate` 成功完成后读取构建请求自动运行；它会拉取 Warp、从 `i18n` 分支选择翻译文件、应用源码替换、生成补丁、在 GitHub runner 上构建，成功后按上游 release 名称发布本仓库 Release。

## 当前策略

Warp 当前没有完整资源化的 i18n 文件，因此本工程采用与 zed-globalization 类似的“外部工具链 + 源码字符串替换 + CI 构建”方案。替换阶段会跳过字节字符串、raw 字符串、属性宏、纯标识符、URL、路径、MIME 类型和占位符不匹配的条目，降低破坏 Rust 语法和运行时协议字符串的风险。

## 许可证

本工具链使用 MIT License。Warp 上游源码遵循其自身许可证。
