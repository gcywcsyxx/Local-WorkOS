# Local WorkOS 产品需求文档（PRD）

> 文档日期：2026-10-03；应用版本：1.3.0；源码基线：`a41728dcb75fe01bbf43a9edc98b743ec21d2c75`。
> 本文区分「当前代码已实现」「已经实测」「拟新增」。未经验证的愿景不等于现有功能。
> 接手开发先读 [AI 工程交接指南](<AI_HANDOFF.md>)；开发源码位于 [仓库根目录](<../>)。本文是公开版，部署域名用示例代替；代码功能基线仍为 a41728d。

## 1. 产品定位

面向 PE / 投资研究的本地优先、单用户、AI-native 工作区。目标是把资料、证据、研究判断、访谈纪要、估值假设和交付物联系起来，而不是堆叠项目管理表单或复制一个通用聊天机器人。

核心价值链：
**项目 → 选定资料 → 原文证据与引用 → 待核实研究结论 → 访谈/模型 → Word/PDF/PPT/Excel 交付 → 后续核实行动。**

### 1.1 已确定的用户偏好
- 中文沟通，投资研究优先；自然语言是主要操作入口，尽量少填表。
- 上传支持点击、拖拽、粘贴；日常研究调用按用户选定范围直接执行，不再增加逐次“同意外发”勾选。
- 登录、CSRF、防止误恢复备份等安全措施不能借此移除。
- DeepSeek V4.1 Flash 优先用于研究问答、行动助手和纪要；GPT/DSH 等作为可选路由。
- 个人记忆 `kind=memory` 只做本机检索，不能发给任何模型；原始记忆文件不自动改写。
- 专家访谈输出参考 PV Expert Call Notes：中性 wording，保留事实/判断/传闻归属、限定条件和不同专家之间的口径差异。
- 文件集中在 OneDrive，活动数据库留本机。公开代码不得混入真实项目材料、账号密码、登录会话或隧道凭据。
- 公网通过独立 Cloudflare tunnel，采用 WorkOS 内置 `workos-user` 账号密码登录，不是 Cloudflare Access / 邮箱 OTP。密码不写本文，仅在主机本地管理。

### 1.2 明确不属于当前版本的能力
企业多用户/RBAC、审计合规系统、自动事实核验、自动 OCR、录音/语音识别、双向跨设备数据库同步、完整三表及多层债务 LBO、从任意资料全自动生成投委会级 IC deck。不能用“已有导出”宣传这些能力已经完成。

## 2. 用户、使用场景与运行条件

| 场景 | 目标 | 当前路径 |
|---|---|---|
| 主机电脑日常研究 | 低步骤整理资料并保留证据 | 本机 `http://127.0.0.1:18866/` |
| 手机/其他电脑远程访问 | 访问同一个主机工作区 | `https://workos.example.com/`，账号登录 |
| 专家访谈整理 | 转写 → 结构化纪要 → 可编辑 Word / PDF | 会议纪要页面 |
| 估值/回报讨论 | 自然语言假设 → 结构化输入 → 本地确定性计算 | 估值与回报模型页面 |
| 交付物制作 | 研究正文/表格/明确图表数据 → 可编辑文件 | 交付中心 |
| 其他 AI 修改功能 | 清楚理解现状与边界，在隔离环境开发 | [Source](<../>) + 本 PRD + [AI_HANDOFF](<AI_HANDOFF.md>) |

**公网依赖主机开机、联网并登录 Windows。** Cloudflare 不是托管运行 Python/SQLite 的云服务器。Windows 用户登录后启动本机服务与独立 connector；若主机休眠、断网或退出运行，外部访问会中断。当前系统只有一个写入权威主机，不要同时在两台电脑用同一 tunnel 启动不同数据库/认证库。

## 3. 需求与现状矩阵

状态说明：A=代码已实现；V=有本机合成数据测试或真实网络验证；P=提出的后续需求，不是承诺已交付。

| ID | 模块 | 当前能力 | 状态 | 关键边界 |
|---|---|---|---|---|
| F01 | 项目/公司 | 阶段、行业、负责人、下一步、关联资料/会议/任务/结论 | A/V | 单用户；无多人权限流 |
| F02 | 快速资料导入 | TXT/MD/PDF/DOCX/PPTX/XLSX/XLSM 抽取、分段、哈希与来源元数据 | A/V | 原始二进制未持久化；扫描 PDF 无 OCR |
| F03 | 研究问答 | 按选中资料检索证据、AI 回答、[S#] 引用、原文定位、保存待核实结论 | A/V | 当前为词法检索片段，不是 embedding 或自动全文推理 |
| F04 | 自然语言行动助手 | 8 个创建/检索工具，最多 6 步 | A/V | 尚不能通过同一工具链直接执行完整纪要/估值/导出工作流 |
| F05 | 会议纪要 | DeepSeek 格式化转写，专家分节、双列比较表、4+专家目录、可编辑摘要自动保存 | A/V | 不是录音识别；仍需核验原文；模板未做全面视觉验收 |
| F06 | 会议导出 | DOCX、bundled LibreOfficeKit PDF，真实 PAGEREF 目录域 | A/V | DOCX 页码域需 Word/Kit 更新；修改纯文本后旧结构会失效 |
| F07 | 四种估值 | P/E、股权 P/S、FCFF DCF、单层债务 LBO；IRR/MOIC | A/V | 无多层债务、期间分红、三表整合等完整模型功能 |
| F08 | Excel 导出 | 输入/公式/结果，Python 原始快照，打开自动重算 | A/V | 活动假设直接下载可用；已保存模型并非可重载的独立对象 |
| F09 | 普通交付导出 | Markdown、可编辑 HTML、DOCX、PPTX | A/V | 普通交付中心未提供通用 PDF 按钮；PPT 不等于完整 IC deck |
| F10 | 原生 PPT 数据块 | Markdown 表格、明确 JSON 的柱/条/线图，嵌入可编辑 Excel | A/V | 数据需明确输入；缺值拒绝，不自动补零/拉网源 |
| F11 | OneDrive | 项目可读文件、JSON 快照、原子替换、previous 版本 | A/V | 单向镜像/备份，不是双向冲突合并；不能用 last_sync 证明云端已上传 |
| F12 | 公网登录 | 单账号密码、HTTPS session、7天记住、CSRF、失败限流、仅本机重设 | A/V | 不做多用户/RBAC；本机其他同用户软件不在隔离边界内 |
| F13 | 原件归档/下载 | 需要保留上传原件并可下载 | P | attachment_* 是占位字段，上传现不写原件 |
| F14 | 可重载模型记录 | method/assumptions/results/source/scenario/version 独立持久化 | P | 现为 deliverable.body 内嵌 JSON；已保存 XLSX 再导出不完整 |
| F15 | 证据版本谱 | 原始文件不可变版本、引用重锚、口径差异及 lineage | P | 现引用仍指向可修改的抽取文本 |

## 4. 核心流程及验收标准

### F02：资料导入
1. 选择项目，可点击选文件、拖拽，或把文本导入研究库。单文件上限约20MB（前后端字节口径略有不同，不能按20MiB边缘值承诺必过）；抽取内容有安全大小上限。
2. 抽取文本和元数据写入本机资料记录；PDF 尽量保留真实页码；DOCX/TXT 等使用段落序号，不能编造 Word 页码。
3. PPTX 读文本；XLSX/XLSM 读公式及缓存值，不刷新外链、不执行宏、不等于真实重算。
4. 正确空白/不支持文件/损坏或超限文件给出可理解错误，不半途宣称已完整导入。
5. 当前没有原件仓库，因此原件丢失不能靠该平台“重新下载原始文件”。

**已发现 P0 交互问题：** 全局 paste handler 除会议转写框外会拦截文本粘贴，可能影响其他输入框；“输入框内正常粘贴”尚须浏览器回归。以后修改应仅在非编辑区或明确导入区执行全局粘贴入库。

### F03：研究问答
- 用户明确选中资料/项目后请求分析；不默认把全库、个人记忆或无关目录交给模型。
- 当前检索返回少量词法相关片段（最多6个 excerpt），带 document_id、页码/段落、摘录及 [S#] 编号。
- 无相关证据时明确回答缺少证据，不拿模型常识冒充来源。
- 服务端可检查 [S#] 是否超出范围；这不是“引用内容支持结论”的语义验证，更不是事实核验。
- 保存结论时保留摘录及来源；默认待核实。界面读的是抽取文本，不是原始文件阅读器。
- 验收：无依据数字不应由系统默认为已核实；点击引用能定位到相应摘录；memory 在模型调用前被硬性拒绝。

### F04：行动助手
当前工具为 import_text、create_project、create_note、create_task、create_meeting、draft_deliverable、search、list_projects。工具改动留下工作区记录。
拟新增高价值工具：按 project_id 取已选 evidence、generate_expert_minutes、calculate_valuation、export_deliverable。每个工具须有类型/范围校验，不让模型执行任意文件或 shell 指令。

### F05/F06：专家纪要
- 原文转写可粘贴或拖入支持的文件，保存 transcript；不是音频→文本服务。
- 输出结构：专家机构/职位/日期；专家背景；关键点评；按主题的访谈内容及 • / o / ➢ 层级。
- 不补造专家身份、任职时间、公司、数字；缺失写“未提及”；保留条件、传闻/判断归属，不合并不同专家矛盾观点。
- 多专家比较目前为竖版两列「议题 / 专家口径」逐专家展开，**不是用户样本中横向多列矩阵的逐像素复刻**。4+专家生成目录，页码通过书签/PAGEREF 取得，不用每位专家一页的猜测。
- experts/matrix/contents 已持久化，重开和备份恢复后可导出。单独手动修改 summary 会失效旧结构，避免导出覆盖人工修改；需要重新生成或未来增加结构化编辑器才能恢复比较表。
- DOCX 参考 A4、中文楷体/英数字 Arial、标题14pt/正文10pt；具体 heading、表格宽度和长文本仍需图像/真实 Office 视觉审阅。
- 输出 DOCX/PDF 必须可打开；PDF 只走已配置的 bundled LibreOfficeKit，不自动寻找替代 Office 程序。Kit 缺失不影响 DOCX，但 PDF 应清楚报错。
- 验收：真实页码域与 PDF 正文一致；源转写、人工修订和导出内容不得错位；年份、型号、前导零、小数和中文单位空格不能被数字格式器改坏。

### F07/F08：估值与回报
**计算原则：AI 只提取明确假设，算术交由 Python；缺失输入不自动当零。**
- P/E：规范化净利润 × P/E → 股权价值；可选稀释后股数。负净利润不强行计算普通 P/E。
- P/S：收入 × 股权 P/S → 股权价值；净债务可桥接隐含 EV。不是 EV/Sales 口径。
- DCF：逐年 EBIT 或收入×利润率、税、D&A、CapEx、ΔNWC → FCFF；WACC、年末/年中折现、永续/退出倍数终值、净债务及少数股东权益桥。
- LBO：进入 EV/债务/费用/最低现金/初始现金/滚存；单层逐年利息/税/强制偿还/cash sweep/现金债务；退出倍数/费用；按真实进入退出日期算 IRR/MOIC。资金缺口明确警示。
- 当前无期间分红、债务 tranches、循环利息、ESOP/IPO dilution、完整三表联动等，不能称为完整投行模型。
- 自然语言假设解析当前是 GPT-6 Luna / DSH 模型路由，不是所有 DeepSeek 路由均已统一接入。模型提取值仍需核对；source_notes 为用户/模型提供元数据，不是已验证的原文映射。
- Excel 应链接可编辑输入，输出分为实时公式与原始 Python 快照；修改退出倍数/费用、继承税/利率和日期等应联动。已经用10份原始/修改后工作簿真实重算，与 Python 引擎核对。
- 边界：收入×EBIT margin 在导出时会物化成 EBIT 数字，不代表经营预测全部字段已动态联动；方法/结构改变通常要重新生成工作簿。
- **保存模型**目前把假设/结果 JSON 放进交付物正文；不是可重载 typed model。已保存记录的 XLSX route 期待不存在的 method/assumptions 字段，需修复；当前页面直接下载 XLSX 正常。

### F09/F10：交付中心
- 正文继续编辑，导出前保存；HTML 可编辑/批注，保存的是独立副本，不回写平台数据。
- PPTX 保留所有文本并自动续页；超过200内容页明确拒绝，不截断。Markdown 表格为可编辑 native table，最长表自动续页，1–6列/单元格160字符的限制会报错而非隐藏值。
- 明确 chart JSON 支持 column/bar/line，带 native chart 和 Excel 数据；分类/系列数量一致且每值为有限数，不把空值当零，不执行 JSON 字符串。
- 保留来源标签/notes；数据需要由用户/研究流程明确提供。完整 IC deck 所需的 storylining、证据映射、可比公司/交易表、品牌模板适配等为后续范围。
- 输出二进制当前交给浏览器下载，不自动归档回项目 Outputs；OneDrive 中的 Outputs 是交付记录文本，不等于生成的 Word/PPT/Excel 原件。

## 5. 模型路由与默认值

| 功能 | 当前默认 | 依赖/注意 |
|---|---|---|
| 界面研究问答 / 行动助手 | deepseek-v4.1-flash | 本机 OpenAI-compatible bridge，默认127.0.0.1:8787/v1；本机桥接不代表离线推理 |
| 会议整理 | deepseek-v4.1-flash | 兼容接口、模型实际权限、连接凭据须可用 |
| 自然语言估值假设 | gpt-6-luna via DSH | DSH CLI及已有账号授权；当前只允许DSH模型集合 |
| API /ask 未指定 mode | local lexical retrieval | 与界面默认AI路由不同 |
| 规则会议备用 | rules | 完全本地，不调用模型 |

模型选择可被已存浏览器偏好覆盖；“检测到DSH”只代表二进制存在，不代表具体模型账号权限可用。自定义 API key 目前仅在服务器内存，重启后需重新配置；不要为了方便把 key 写到源码或 PRD。

## 6. 数据与同步契约

### 6.1 数据对象
- projects：name/sector/stage/priority/thesis/next_step/owner/valuation/tags。
- documents：research 或 memory；content/chunks/hash/source_ref/filename/page_count 等；attachment_* 目前只是占位。
- meetings：transcript/summary + experts/matrix/contents；专家索引和矩阵维度均要验证。
- notes：body/status/document_id/source_quote；证据摘录是副本，不是不可变原件链接。
- tasks：status/priority/due/owner/project_id/meeting_id。
- deliverables：title/project_id/kind/body；没有独立model字段。
- activity：操作事件的简要记录。

### 6.2 文件与数据库
活动 personal/demo SQLite、认证库及会话库留在 `%LOCALAPPDATA%/LocalWorkOS`。OneDrive 存项目 JSON/抽取文本/工作区快照。
镜像主要结构为 Projects/{id_name}/project.json、Sources、Meetings、Research、Actions、Outputs；未关联资料进 Inbox/Sources；Sync 保存 personal/demo 的可重建JSON快照。
变更写入时原子替换，旧内容以 `.previous-<hash>` 保留；删除/改名可能保留旧可读镜像文件，当前没有完善清理/合并。
**last_sync 是本机写文件时刻，不证明 OneDrive 已完成上传，也不是跨机器实时事务一致性。** 当前无周期性拉取、双向冲突合并或多主写入。

## 7. 安全与运行要求

- 公网固定HTTPS；后端仍监听回环18866，不将Python服务直接绑定0.0.0.0。
- 当前运行 `WORKOS_PUBLIC_AUTH_MODE=password`；legacy Access mode 可选，但不等于当前部署采用 Access。
- 用户 `workos-user`；密码只在主机管理；仅存随机盐PBKDF2-SHA256（600000次）哈希。登录会话标识哈希本机存储，不能同步至OneDrive/Git。
- Cookie 为 Secure / HttpOnly / host-only；不记住12小时、记住7天，并跨应用重启保留；注销/重设密码使会话失效。
- 登录提交前自动获取新nonce/cookie；挑战失效可自动恢复一次，明确提示Cookie阻止；换网/IPv4/IPv6不硬性绑定挑战IP（IP仅用于限流），仍有来源约束、失败限流；公网全部数据API/下载需登录，写入仍校验每session CSRF；本机可信请求不需要公网登录。
- `/auth/setup` 仅本机、需本机CSRF；不能通过公网初始化/重设密码，包括Host被改写为localhost的转发请求。
- 不记录密码/token/原始鉴权header；不读取Chrome cookie当作Cloudflare或GitHub授权。
- 不触碰共享dsh tunnel；独立WorkOS连接器重复启动应幂等；启动设置不包含明文密码。

## 8. 优先级明确的后续需求（拟新增）

| 优先级 / ID | 需求 | 建议验收 |
|---|---|---|
| P0 / B01 | 输入框正常粘贴与全局导入边界 | 除明确导入区，所有input/textarea/contenteditable保留Ctrl+V正常行为；移动端同测 |
| P0 / B02 | 原件本机归档、哈希去重、下载与OneDrive原件镜像 | 上传原件可重新下载且SHA一致；提取文本版本与原件关联；memory仍不外发 |
| P0 / B03 | typed model持久化与saved XLSX重新导出 | 保存→重启→载入→改场景→重算→导出；方法/单位/来源/版本完整 |
| P0 / B04 | 更新依赖声明与CI安装依赖 | 干净Windows/Linux环境能装齐Word/PPT/Excel测试依赖并跑CI；不把本机测试当CI成功 |
| P1 / B05 | AI工具链覆盖纪要/估值/导出 | 一条自然语言任务能按明确project/source范围串联，缺输入只问关键问题 |
| P1 / B06 | 不可变原件版本和引用锚点 | 修改原文不让旧引用悄悄指向新内容；对过期引用给出提示 |
| P1 / B07 | 项目交付实体文件/修订谱 | DOCX/PDF/PPTX/XLSX生成后可选择归档项目，保留前版及generation来源 |
| P1 / B08 | 模型解析路由统一与连接状态检测 | 显式可选DeepSeek或DSH解析；检测账号/模型可用，避免仅检查exe |
| P1 / B09 | PV模板与结构化专家编辑 | 真实用户模板可用；矩阵、目录、长段落视觉验收；修改专家内容不必丢整个矩阵 |
| P2 / B10 | OCR/腾讯会议转写导入 | 在明确授权范围获取原文；OCR标注不确定文本，不装成已核验事实 |
| P2 / B11 | 更丰富财务模型与IC deck storylining | 明确建模口径、债务/分红/股权结构，图表/结论各有source，不用LLM代算 |
| P2 / B12 | 更成熟同步/备份与监控 | OneDrive上传状态/冲突可见；保留单主机原则或设计完整合并，不同步SQLite/WAL |

## 9. 发布验收清单

- 单元+HTTP套件在独立临时数据目录通过；当前基线160测试，157通过/3跳过，不代表以后必须固定这个数字。
- 原件/导出/表格/图表内容不被静默截断；对于不支持格式明确报错。
- 模型算术与确定性Python输出/实际Office重算核对；假设提取错误不自动成为事实。
- 公网匿名首页进入登录页；匿名bootstrap/state/backup/exports无数据；正确账号可进入；伪Cookie/跨站/缺CSRF拒绝；注销生效。
- 重启不丢已记住的session；活动SQLite与密码/会话文件不进OneDrive。
- 测试不能对真实个人库写合成数据；公开Git diff不能含项目材料、密码、token或机器配置文件。
- 如做视觉验收，必须实际能看渲染图片；结构/页数/文本抽取通过不能叫“没有裁切”。
- OneDrive源码修改不会自动热更新线上服务；必须测试→明确安装发布→健康/鉴权/镜像复核。

## 10. 当前验证证据与未验证项

基线本机验证：Word/PDF实际目录页码、多专家SQLite重开与backup/restore、10份估值原始/修改工作簿原生重算、PPT全正文/表格/native chart/embedded workbook、真实HTTPS登录/匿名拒绝/CSRF/注销/session重启持久化。公网已上线，主机仍需保持运行。
尚未核实最新GitHub Actions绿色状态；没有广泛模型回答准确率benchmark；没有完成当前导出文件的图片视觉审阅。详细工程命令和修改流程见 [AI_HANDOFF](<AI_HANDOFF.md>)。
