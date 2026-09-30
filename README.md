# Local WorkOS

本地优先的单用户研究与项目工作平台。项目、资料与引用、会议、任务、记忆、回报测算和交付物共享同一数据模型。

A local-first research and project workspace with evidence-grounded retrieval, meeting action review, deterministic return modelling and editable deliverables.

## 启动 / Run

需要 Python 3.11+，无 Node、CDN 或前端构建依赖。

```shell
python launch.py
```

打开 `http://127.0.0.1:18866`。重复启动复用同一平台实例；停止使用 `python launch.py --stop`。仅绑定本机回环地址；Windows 使用独占端口，不覆盖其他应用的监听。

Windows 可用 [安装辅助脚本](<tools/install.ps1>) 部署并建立开始菜单入口。若系统签名策略拒绝运行，不要为了本工具修改系统策略；也可直接运行Python启动器。不开机自启，不注册系统服务。

可选Word导出依赖：

```shell
python -m pip install -r requirements.txt
```

运行库与数据库不进入Git仓库。Windows默认在 `%LOCALAPPDATA%/LocalWorkOS`，其他系统在 `~/.local/share/LocalWorkOS`。个人与演示使用独立SQLite数据库。

## 功能 / Features

- **公司与项目**：阶段、行业、负责人、下一步，关联资料/会议/任务/结论。
- **研究工作台**：TXT、Markdown、PDF和DOCX文本导入；显式选择资料，本地关键词召回与原文引用。PDF引用真实页码，无排版页码时用段落。
- **会议中心**：规则提取行动候选；人工逐项确认后才生成任务，不猜测负责人或截止日期。
- **任务中心**：状态、优先级、日期与项目关联，修改持久保存。
- **知识与记忆**：默认关闭本机目录扫描；只在显式配置 `WORKOS_MEMORY_ROOT` 后启用只读导入。来源文件不被修改，记忆不得发送到外部模型。
- **回报测算**：确定性简化税前模型、现金流、情景和敏感性。固定进入价格，现金不重复计入，不把中间留存现金当分红。
- **交付中心**：可编辑结论、Markdown/HTML/可选Word导出。导出HTML自带独立编辑器，支持修改正文、选文批注及下载保存副本；重新打开保留内容和批注，不回写数据库。
- **设置**：按工作区备份恢复；可选OpenAI-compatible接口，密钥只在服务器内存，每次问题单独确认所选资料的外发授权。

本地检索不是LLM推理，规则会议草稿不是录音转写；引用能定位原文不代表原文事实已核实。真实模型调用需要用户自行配置接口和授权，未配置时不会生成假模型答案。

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

这是本机单用户原型，不是企业多用户系统。未实现邮件/聊天发送、录音、OCR、PPT生成、云同步、完整LBO、事实自动验证或企业级权限控制。不应直接绑定公网地址部署。

HTML编辑器仅支持纯文本段落编辑与同段选文批注，保存为新HTML文件。未实现跨段批注、正文改变后的自动重锚或原文件授权写回。

## 第三方与许可 / Licensing

pypdf 6.18.1使用BSD-3-Clause，原版权与许可证保留在 [第三方许可证](<vendor/pypdf-LICENSE.txt>)。Word依赖python-docx按其自身许可安装，不在仓库复制。

HTML编辑器在本仓库中独立实现，不包含内部技能资产。本次仅公开源代码，尚未授予项目级开源许可；第三方组件按各自许可使用。
