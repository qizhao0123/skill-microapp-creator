# skill-microapp-creator 补充使用说明

本 skill 用于按 App Deployer `deploy.xzd5/v1` 契约创建新 Web 应用、改造旧应用、发布代码或环境配置更新，以及生成只更新持久化数据的 DataPatch。

## 安装

将仓库克隆到 Codex skills 目录：

```text
git clone https://github.com/qizhao0123/skill-microapp-creator.git <CODEX_HOME>/skills/skill-microapp-creator
```

Windows 常见目录：

```text
C:\Users\<用户名>\.codex\skills\skill-microapp-creator
```

安装后在新任务中使用 `$skill-microapp-creator` 显式调用。

## 常用请求

### 创建新应用

```text
使用 $skill-microapp-creator 根据下面的业务需求创建一个兼容 App Deployer 的新应用。先确认入口、二级目录、环境变量和持久化边界，再开发、验证并生成标准 ZIP。

[业务需求]
```

### 改造旧应用

```text
使用 $skill-microapp-creator 将当前旧应用改造成兼容 App Deployer 的标准应用。先只读审计真实启动入口、根路径 URL、配置来源和数据写入位置，再实施最小范围改造，保留现有业务和数据。
```

### 日常代码更新

```text
使用 $skill-microapp-creator 完成本次功能需求，保持现有 app.yaml 的应用身份、路由模式和持久化模式不变，提升 SemVer，运行验证并生成新应用 ZIP。

[本次需求]
```

### 只更新数据

```text
使用 $skill-microapp-creator 检查当前生效 manifest 是否允许更新 reports；若允许，只生成 DataPatch，不修改源码、不提升应用 SemVer、不发布线上数据。所有 JSON 需要执行语法校验。

[数据目录和删除清单]
```

## 选择代码发布还是 DataPatch

| 变化内容 | 交付方式 |
|---|---|
| 源码、HTML、JS、CSS、程序模板、Dockerfile、`app.yaml` | 提升 SemVer，生成完整应用 ZIP |
| 生产环境变量值 | 提升 SemVer，上传新版本后创建配置修订 |
| 与代码版本强关联的图片或静态资源 | 完整应用 ZIP |
| 当前生效 manifest 已声明 `mutablePaths` 内的 JSON、CSV、PDF、业务图片 | 独立 DataPatch revision |
| 同时包含代码和可变数据 | 完整应用 ZIP；必要时再拆分后续 DataPatch |

如果目标目录尚未进入当前生效版本的 `mutablePaths`，必须先发布并激活一个更高 SemVer 的代码版本。不能通过 DataPatch 绕过 allowlist。

## 核心交付规则

- 动态应用监听平台注入的 `HOST=0.0.0.0` 和 `PORT`。
- 动态路由优先使用 `native`，页面、资源、API、跳转、下载和 Cookie Path 原生支持 `APP_BASE_PATH`。
- 所有业务配置由环境变量读取并在 `spec.env` 声明；不提交真实 `.env` 或密钥默认值。
- 所有文件型持久化数据写入 `/app/data`；初始化数据只放 `seed/data`，且仅在数据目录为空时复制。
- 健康检查必须是不登录、无副作用的 GET；smoke test 只使用 GET/HEAD。
- 应用 ZIP 根目录包含 `app.yaml`、Dockerfile、`.dockerignore`、源码和锁文件，不包含 Compose、Nginx、生产数据、`.git` 或 `node_modules`。
- 上传只形成 `READY`，不会自动切换生产；发布或“发布数据”必须获得单独明确授权。
- 用户数据库、用户上传、提交记录等默认为受保护数据，不能放进 `mutablePaths`；未知数据也按受保护处理。
- 只产生用户数据、不需要资源数据更新的应用使用 `files` 和空 `mutablePaths`。
- 同时存在后台资源和用户数据时必须分目录，只允许后台资源目录通过 DataPatch 更新。

## 工具

只读审计：

```text
python scripts/audit_microapp.py <project-dir> --format markdown
```

生成 DataPatch：

```text
python scripts/build_data_patch.py --app <app-name> --revision <revision> --target <mutable-path> --active-manifest <active-app.yaml> --data-inventory <completed-inventory.json> --files <data-dir> --validate-json --output <patch.zip>
```

数据清单从 `assets/data-safety-inventory.json` 复制，必须匹配当前生效版本，并完整列出后台维护目录和受保护目录；确认完成后才能设置 `complete: true`。构建器会校验 Manifest 与清单边界并生成 `.safety.json` 外部证据文件。如包含 `--delete`，还必须在用户确认精确删除清单后增加 `--confirm-delete`。`--validate-json` 只检查 `.json` 后缀、UTF-8 和 JSON 语法，不验证业务字段。revision 唯一性也必须在目标应用控制面确认。

## 规范索引

- 应用 Manifest 说明：[APP_MANIFEST.md](APP_MANIFEST.md)
- 应用 Manifest JSON Schema：[app.schema.json](app.schema.json)
- DataPatch 说明：[DATA_UPDATE.md](DATA_UPDATE.md)
- DataPatch JSON Schema：[data-update.schema.json](data-update.schema.json)
- 平台核心约束摘要：[platform-contract.md](platform-contract.md)
- 新建、改造、更新流程：[workflows.md](workflows.md)
- 验证和交付边界：[verification.md](verification.md)
- 用户数据安全门禁：[DATA_SAFETY.md](DATA_SAFETY.md)

这些规范是随 skill 打包的快照。工作区存在 live `app-deployer` 时，优先读取 live 文档和实现，并使用当前源码版 `deployctl validate`，不要静默依赖可能过期的二进制。
