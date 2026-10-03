# Local WorkOS

本地优先的单用户研究与项目工作平台。项目、资料与引用、会议、任务、记忆、回报测算和交付物共享同一数据模型。

A local-first research and project workspace with evidence-grounded retrieval, meeting action review, deterministic return modelling and editable deliverables.

## 产品与开发交接 / Product and AI handoff

- [当前PRD：已实现、边界、优先级与验收](<docs/PRD.md>)
- [AI工程交接：架构、隔离测试与发布](<docs/AI_HANDOFF.md>)
- [完整开发测试依赖](<requirements-development.txt>)

部分下文为历史说明；最新功能与安全契约以上述PRD和交接指南为准。

## 启动 / Run

核心仅需 Python 3.11+，无 Node、CDN 或前端构建依赖。要使用 GPT/DSH，需本机已有登录的 DSH CLI；WorkOS 不会复制 OAuth 密钥。

```shell
python launch.py
```

打开 `http://127.0.0.1:18866`。重复启动复用同一平台实例；停止使用 `python launch.py --stop`。仅绑定本机回环地址；Windows 使用独占端口，不覆盖其他应用的监听。

Windows 可用 [安装辅助脚本](<tools/install.ps1>) 部署并建立开始菜单入口；本机启动快捷方式可选开机自启。公开默认仍只绑定回环地址；公网必须使用受保护的独立隧道：支持内置账号密码模式或经配置的Cloudflare Access模式，不能直接开放端口。参见 [密码公网部署](<docs/password-public.md>)。

可选Word导出依赖：

```shell
python -m pip install -r requirements.txt
```

运行库与数据库不进入Git仓库。Windows默认在 `%LOCALAPPDATA%/LocalWorkOS`，其他系统在 `~/.local/share/LocalWorkOS`。个人与演示使用独立SQLite数据库。

## 功能 / Features

- **公司与项目**：阶段、行业、负责人、下一步，关联资料/会议/任务/结论。
- **研究工作台**：TXT、Markdown、PDF和DOCX文本导入；一键项目速览、尽调缺口与口径差异提纲；GPT/DSH分析选定证据，回答保留页码/段落引用，可保存为待核实结论。
- **会议纪要**：粘贴转写后可调用 DeepSeek V4.1 Flash 生成 PV Expert Call Notes 风格草稿（专家背景/点评/访谈内容，•/o/➢层级）；本机保存、可编辑，并导出楷体风格 DOCX 与 PDF。模型无法识别的身份/数字不得补造；导出前应复核。Word/PDF使用已配置的 LibreOffice Kit。若Kit不可用，Word仍可下载，PDF会提示配置问题。
- **任务中心**：状态、优先级、日期与项目关联，修改持久保存。
- **知识与记忆**：可在个人工作区直接选择 TXT/MD/PDF/DOCX 文件，或一次选取文件夹导入；无需配置路径。原文件不修改，内容经凭证/路径过滤后只保存在本机，记忆只允许本地检索、不发送给模型。可选 `WORKOS_MEMORY_ROOT` 扫描仍保持显式授权。
- **回报测算**：确定性简化税前模型、现金流、情景和敏感性。固定进入价格，现金不重复计入，不把中间留存现金当分红。
- **交付中心**：可编辑结论、Markdown/HTML/可选Word导出。导出HTML自带独立编辑器，支持修改正文、选文批注及下载保存副本；重新打开保留内容和批注，不回写数据库。
- **GPT / DSH**：默认通过本机 DSH 接 ChatGPT OAuth 路由，默认 GPT-6 Luna，不需要在 WorkOS 粘贴 API Key；提问按当前勾选范围直接发送证据，不额外弹授权，只发送已选资料，个人记忆仍只做本地检索。会话、日志、标题与遥测在返回后从临时目录清理。也支持可选 OpenAI-compatible 接口。

本地检索不是LLM推理，规则会议草稿不是录音转写；引用能定位原文不代表原文事实已核实。GPT/DSH调用使用你已有的 DSH 登录与模型权限；未检测到 DSH 时仍可使用本地检索或自行配置兼容接口。模型回答始终是待核验草稿。

## 演示与隐私 / Demo and privacy

通过侧栏切换到**演示工作区**，公司、人物、资料和会议均为明确标记的合成数据。个人区首次使用为空，演示区不扫描真实记忆。

公开仓库不包含私人记忆、简历、真实交易资料、数据库、备份、日志、密钥、个人路径或机器环境档案。原始内部软件与公开版本是独立目录和数据空间。

凭证过滤是尽力而为，不能保证完整匿名化。备份、导出报告及模型调用均可能包含用户自行导入的敏感材料，分享前需人工复核。不要把数据库、个人备份或真实资料提交到此仓库。

## 测试 / Testing

从项目根目录运行，pypdf已随包提供源码：

```powershell
$env:PYTHONPATH = "$PWD\vendor"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m unittest discover -s tests -v
```

Linux/macOS：

```shell
PYTHONPATH=vendor PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

浏览器脚本使用可选Playwright和本机Chrome，只生成临时合成内容。不要针对真实个人数据库运行会写数据的工作流测试。

```shell
python -m pip install playwright
python -m tests.browser_export
```

浏览器整合回归需要单独启动测试端口和临时数据目录，再通过 `WORKOS_E2E_URL` 指定工作流测试地址（烟测使用 `WORKOS_TEST_URL`）；脚本见 [工作流测试](<tests/browser_workflows.py>)。默认不会自动连接生产数据库。

## 边界 / Scope

这是本机单用户原型，不是企业多用户系统。未实现邮件/聊天发送、录音、OCR、自动化PPT生成、完整LBO、事实自动验证或企业级权限控制。OneDrive仅镜像项目文件与JSON快照，不同步活动SQLite。不应直接绑定公网地址部署。

HTML编辑器仅支持纯文本段落编辑与同段选文批注，保存为新HTML文件。未实现跨段批注、正文改变后的自动重锚或原文件授权写回。

## 第三方与许可 / Licensing

pypdf 6.18.1使用BSD-3-Clause，原版权与许可证保留在 [第三方许可证](<vendor/pypdf-LICENSE.txt>)。Word依赖python-docx按其自身许可安装，不在仓库复制。

HTML编辑器在本仓库中独立实现，不包含内部技能资产。本次仅公开源代码，尚未授予项目级开源许可；第三方组件按各自许可使用。
