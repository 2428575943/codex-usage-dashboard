# Codex 额度守护（0.1.2 预览版）

Windows 10/11 x64 的独立社区工具，读取本机 Codex 账号的官方 5 小时剩余额度，生成模型目录并维护配置。与原 Codex Usage Monitor 分开运行，不修改原采集器或统计数据库。

## 规则

| 5 小时剩余 | 启动菜单允许的模型 |
|---|---|
| 大于 30% | GPT-6.1 Terra、GPT-6.1 Sol、GPT-6 Luna；本机官方目录实际出现 GPT-6.2 Sol 后才加入 |
| 15% 至 30%（含两端） | GPT-6.1 Terra、GPT-6 Luna |
| 小于 15% | GPT-6 Luna |
| 未知、失效、无法查询 | GPT-6 Luna |

上述可见模型仅提供 `low`、`medium`、`high`（轻度、中、高）。保留内部隐藏的自动安全审核模型，不将其加入菜单。

## 当前能力与边界

- 使用官方 `model_catalog_json`、`model`、`model_reasoning_effort` 配置以及桌面端的强度菜单设置。
- 模型目录在启动时加载。切档后需完整退出并重新打开 Codex；不会自动结束或重启正在工作的聊天。
- **不是逐轮强制执行器。已有聊天保存的选择、显式覆盖、其他配置文件/远程会话可能绕过本机启动菜单。不能承诺“运行中立刻只能使用这些模型”。**
- 不修改 Codex.exe、ChatGPT.exe、安装目录或应用资源，不注入进程。
- 每次使用前检测当前组件路径；组件或模型元数据变化时先调用实际组件的 `model/list` 验证目录解析和强度。检查失败则显示错误，不继续写配置。
- 每 3 分钟最多一次主动额度查询；软件更新最多每 24 小时检查一次。失败、重启和手动刷新保留间隔。数据超过 10 分钟或跨越重置时间后失效。
- 不上传聊天、登录凭据或个人额度；账号标识只在本机保存单向摘要。Rust 组件复用现有 Windows 系统代理，不修改代理设置。
- 原配置完整备份，恢复时只撤销仍由工具持有的键，保留用户后续改动。
- 其他第三方自定义模型目录已启用时停止应用，避免覆盖。
- 组件升级后的自动兼容检查是防护措施，不能证明所有未来 Codex 版本都支持该接口。

## 安装与恢复

运行 `codex-quota-guard-0.1.2-setup.exe`，标准 Inno Setup 当前用户安装，无需管理员权限或额外 Python。安装完成后自动后台启动，并注册当前用户登录启动项。双击桌面的“Codex 额度守护”查看状态。

状态窗口的“停用并恢复”会停止轮询、移除登录启动项并恢复管理过的配置。标准 Windows 卸载同样先恢复配置，再删除程序文件。恢复失败则中止卸载，保留恢复工具。备份保留在 `%LOCALAPPDATA%\CodexQuotaGuard`。

托盘菜单中的“退出守护”仅退出程序，保留已写入的配置。再次打开工具将重新启用。

## 更新

更新源使用本仓库独立分支的 `release/latest.json`，GitHub Releases 保存完整安装包。不依赖 Render 或个人电脑常开。

客户端只接受固定 Ed25519 公钥签名、正确产品标识、递增序号、受限 HTTPS 来源和相符 SHA-256 的完整安装包。先验证再调用标准安装程序；升级前停止自己的守护程序，安装后自动启动。更新安装重试也限制为每天一次。首次下载仍可能遇到 Windows SmartScreen 的未签名发布者提示。

**以交付说明中的实际发布状态为准。代码、签名测试通过不等于更新源已经上线，也不等于跨版本自动更新已经现场验证。**

## 杀毒软件

采用标准安装器、原版 Python 运行时和普通 Windows 程序，避免脚本执行策略绕过、加壳和关闭安全防护。不能保证所有杀毒软件永不误报。Ed25519 更新签名与 Windows Authenticode 发布者签名是两回事。

## 构建及维护

Python 3.12，`cryptography` 用于更新验签；标准 Inno Setup 6.7.4。`python -m unittest discover -s tests -v` 验证策略、配置恢复、数据时效和更新验证。

`python build.py --runtime-source <Python目录> --iscc <ISCC.exe>` 生成安装包。`runtime.py --dry-run` 可读取当前账号额度并校验实际组件，不改 Codex 配置；`--offline` 不主动查询额度或更新服务器。

正式发布流程：CI 生成安装包及 SHA256SUMS → 维护者用保存在本机的私钥签署发布清单 → 上传 `release/latest.json`。私钥不得进入仓库或客户端。

官方接口参考：[配置说明](https://learn.chatgpt.com/docs/config-file/config-reference)、[App Server](https://learn.chatgpt.com/docs/app-server)。
