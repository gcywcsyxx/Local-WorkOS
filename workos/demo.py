"""Synthetic-only demo workspace. No real memory or external files are read."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib

from .engine import chunk_text, meeting_draft


def _sim(*lines: str) -> str:
    """Every nonempty source line explicitly labels itself as simulated."""
    return "\n".join("[模拟] " + line for line in lines)


def demo_data() -> dict:
    """Return fresh, referentially complete synthetic records using relative dates.

    IDs are stable for seed/reset; due dates and source dates are relative to today.
    Financial and business claims are fabricated solely to demonstrate workflows.
    """
    today = date.today()
    now = datetime.now(timezone.utc)
    previous_year = today.year - 1
    day = lambda offset: (today + timedelta(days=offset)).isoformat()

    def record(record_id: str, *, age: int = 10, **fields) -> dict:
        return {"id": record_id,
                "created_at": (now - timedelta(days=age)).isoformat(timespec="seconds"),
                "updated_at": now.isoformat(timespec="seconds"), **fields}

    projects = [
        record("demo-project-beichen", name="北辰机器人（合成）", sector="工业机器人", stage="尽调", priority="高",
               thesis="[模拟] 验证柔性装配产品的客户复购和服务收入，不将预测当成已实现业绩。",
               next_step="[模拟] 对齐管理层预测与未审管理账的收入范围，补齐验收证据。", owner="模拟研究员甲",
               valuation="[模拟] 尚未形成估值结论", tags="合成演示,收入核对,客户验证"),
        record("demo-project-yuanshan", name="远山算力（合成）", sector="算力服务", stage="初筛", priority="高",
               thesis="[模拟] 区分规划容量、已安装容量、验收容量及在租容量，核实电力成本。",
               next_step="[模拟] 获取容量口径桥接表及含电力成本的毛利测算。", owner="模拟研究员乙",
               valuation="[模拟] 初筛，未报价", tags="合成演示,算力,口径待核实"),
        record("demo-project-chengchuan", name="澄川工业（合成）", sector="工业零部件", stage="投委会", priority="中",
               thesis="[模拟] 以客户集中度、现金转换与退出倍数下行为核心压力测试。",
               next_step="[模拟] 将回报模型假设与未核实风险一并写入投委草稿。", owner="模拟研究员丙",
               valuation="[模拟] 进入 EV 512 百万元，仅算术示例", tags="合成演示,投委草稿,回报测算"),
        record("demo-project-nanyu", name="南屿储能（合成）", sector="储能设备", stage="线索", priority="低",
               thesis="[模拟] 先核实中试和商业交付的边界，不以规划产能代替订单。",
               next_step="[模拟] 明确首批商业客户与验收材料是否存在。", owner="模拟研究员甲",
               valuation="", tags="合成演示,早期线索"),
    ]
    p1, p2, p3, p4 = (project["id"] for project in projects)

    source_specs = [
        ("demo-source-beichen-plan", p1, "北辰机器人｜管理层预测口径（合成）", "management-forecast.md",
         _sim("合成资料：公司、人物及经营数字均为虚构，不对应真实企业。",
              f"记录日期：{day(-45)}；讨论期间：{previous_year} 年全年；来源类型：管理层预测演示。",
              f"北辰机器人预测 {previous_year} 年收入为 240 百万元，EBITDA 为 36 百万元，尚未经审计。",
              "预测口径包括未最终验收项目及代理代采收入；不能直接视为已确认收入。",
              f"{previous_year} 年订单统计为 180 百万元，其中含 40 百万元意向订单；订单不是收入。",
              "待核实：获取按客户、验收状态与收入确认政策拆分的桥接表。")),
        ("demo-source-beichen-ledger", p1, "北辰机器人｜未审管理账摘录（合成）", "management-ledger.md",
         _sim("合成资料：以下数字专为展示证据引用与待核实差异而编造。",
              f"记录日期：{day(-10)}；讨论期间：{previous_year} 年全年；口径：未审管理账。",
              f"北辰机器人 {previous_year} 年管理账收入为 218 百万元，EBITDA 为 28 百万元。",
              "管理账口径不含未最终验收项目，代理代采按净额展示；预测资料使用不同范围。",
              "240 与 218 百万元存在 22 百万元差异；尚无完整桥接，不能把差异直接解释为经营恶化或资料造假。",
              "最近一个季度新增订单为 68 百万元；该季度流量与全年订单 180 百万元的时间范围不同，不应直接判为冲突。",
              "待核实：样本客户合同、验收时点、毛额/净额调整及退换货条款。")),
        ("demo-source-yuanshan-plan", p2, "远山算力｜扩容沟通记录（合成）", "capacity-plan.md",
         _sim("合成访谈记录：所有公司名称、卡数与利润率均为模拟数据。",
              f"访谈日期：{day(-25)}；时间范围：未来一个季度；口径：扩容规划。",
              "远山算力计划未来一个季度达到 8,000 卡，尚未完成交付；其中 4,000 卡对应意向沟通，不等于已签约收入。",
              "讨论中的毛利率 33% 不含电力与部分机房运营成本，不是全成本口径。",
              "待核实：电力接入、硬件交期、客户意向转正式合同的条件。")),
        ("demo-source-yuanshan-operations", p2, "远山算力｜当前运营快照（合成）", "operations-snapshot.md",
         _sim("合成运营快照：不是实地调查结果，不对应任何真实算力设施。",
              f"快照日期：{day(-3)}；时间范围：当日存量；口径：实际安装、验收、在租分别列示。",
              "远山算力当前已安装 4,200 卡，已验收 3,400 卡，在租 3,000 卡；三者定义不同。",
              "未来规划 8,000 卡与当日已安装 4,200 卡并非相同时间或状态，不能据此断定前后矛盾。",
              "包含电力与机房运营成本的毛利率示例为 21%；与不含上述成本的 33% 不能直接比较。",
              "待核实：验收清单、租赁合同起租日及 33% 到 21% 的成本桥接。")),
        ("demo-source-chengchuan-committee", p3, "澄川工业｜投委假设表（合成）", "committee-assumptions.md",
         _sim("合成投委演示：所有假设仅为模型算术示例，不构成投资建议。",
              f"资料日期：{day(-7)}；基准期：{previous_year} 年；金额单位为人民币百万元。",
              "澄川工业初始收入 320，EBITDA 利润率 20%，由此初始 EBITDA 为 64。",
              "进入 EV/EBITDA 倍数为 8x，进入 EV 为 512；初始债务占 EV 的 30%，不是 30x 杠杆。",
              "假设年增长 10%、退出倍数 8x、持有期 5 年、税前现金转换率 65%、债务利率 7%。",
              "现金流先偿债、余款保留至退出；中间无分红。该示例未单列所得税、交易费用及融资约束。",
              "待核实：客户集中度、资本开支、现金转换率的历史持续性；假设一致不等于企业事实已核实。")),
        ("demo-source-nanyu-screening", p4, "南屿储能｜早期线索备忘（合成）", "early-screening.md",
         _sim("合成早期线索：人物、客户与业务规划均为虚构。",
              f"记录日期：{day(-4)}；来源类型：早期沟通模拟，未经核实。",
              "南屿储能提出 20 MWh 中试计划；中试规划不是商业出货，也不是可确认收入。",
              "首批商业客户、订单金额与验收时间尚未明确；本资料不提供收入预测。",
              "下一步仅为确认中试进度和客户验证路径，不作投资结论。")),
    ]
    documents = []
    for record_id, project_id, title, filename, content in source_specs:
        documents.append(record(record_id, title=title, project_id=project_id, kind="research",
                                category="合成演示资料", source_ref="synthetic://local-workos/" + filename,
                                content=content, filename=filename, private=False, page_count=1,
                                hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                chunks=chunk_text(content)))

    north_transcript = _sim(
        f"会议日期：{day(-1)}；这是合成逐字稿，参会者为模拟研究员甲、模拟研究员丁。",
        "模拟研究员甲：预测收入 240 与管理账 218 的范围不一致，暂时不能把 22 的差异解释为业绩下滑。",
        "模拟研究员丁：需要分别检查未验收项目及代理代采按净额调整，尚未取得桥接。",
        f"下一步：核对收入范围与验收政策；负责人：模拟研究员甲；截止：{day(-1)}。",
        f"待办：抽样访谈三类客户；负责人：模拟研究员丁；截止：{day(2)}。",
        "行动项：补充客户验收证据，负责人待定，未约定日期。")
    far_transcript = _sim(
        f"会议日期：{day(-2)}；这是合成逐字稿，参会者为模拟研究员乙、模拟研究员丙。",
        "模拟研究员乙：8,000 是未来规划，4,200 是当前已安装，不能当作同口径冲突。",
        "模拟研究员丙：33% 与 21% 是否可桥接仍需原始成本明细，不能直接解释为毛利恶化。",
        f"下一步：区分规划、安装、验收与在租卡数；负责人：模拟研究员乙；截止：{day(0)}。",
        f"待办：取得含电力成本的毛利桥接；负责人：模拟研究员丙；截止：{day(3)}。",
        "模拟研究员乙：没有形成投资结论。")

    def labeled_summary(transcript: str) -> str:
        # The generated draft is still explicitly simulated on every displayed line.
        return _sim(*meeting_draft(transcript)["summary"].splitlines())

    meetings = [
        record("demo-meeting-beichen", title="北辰机器人｜收入范围核对会（合成）", project_id=p1,
               date=day(-1), participants="模拟研究员甲、模拟研究员丁", transcript=north_transcript,
               summary=labeled_summary(north_transcript)),
        record("demo-meeting-yuanshan", title="远山算力｜容量与成本口径会（合成）", project_id=p2,
               date=day(-2), participants="模拟研究员乙、模拟研究员丙", transcript=far_transcript,
               summary=labeled_summary(far_transcript)),
    ]
    m1, m2 = (meeting["id"] for meeting in meetings)
    tasks = [
        record("demo-task-income", title="[模拟] 核对收入范围与验收政策", project_id=p1, status="进行中", priority="高",
               owner="模拟研究员甲", due=day(-1), description="[模拟] 由北辰会议候选确认；对齐 240/218 百万元的范围，不先下事实冲突结论。", meeting_id=m1),
        record("demo-task-customers", title="[模拟] 抽样访谈三类客户", project_id=p1, status="待办", priority="高",
               owner="模拟研究员丁", due=day(2), description="[模拟] 由会议行动项确认；分别检查合同、验收与收入确认时点。", meeting_id=m1),
        record("demo-task-acceptance", title="[模拟] 补充客户验收证据", project_id=p1, status="待办", priority="中",
               owner="", due="", description="[模拟] 候选转任务后仍未指定负责人和截止日，不自动填入承诺。", meeting_id=m1),
        record("demo-task-capacity", title="[模拟] 区分规划、安装、验收与在租卡数", project_id=p2, status="进行中", priority="高",
               owner="模拟研究员乙", due=day(0), description="[模拟] 关联两份不同日期/状态资料，建立口径桥接而非机械判为冲突。", meeting_id=m2),
        record("demo-task-power", title="[模拟] 取得含电力成本的毛利桥接", project_id=p2, status="待办", priority="高",
               owner="模拟研究员丙", due=day(3), description="[模拟] 核对不含电力 33% 与全成本 21% 的定义，暂不做趋势结论。", meeting_id=m2),
        record("demo-task-model", title="[模拟] 完成基准和下行情景算术检查", project_id=p3, status="完成", priority="中",
               owner="模拟研究员丙", due=day(-2), description="[模拟] 已完成仅指合成假设的计算检查，不是财务尽调通过。", meeting_id=""),
        record("demo-task-committee", title="[模拟] 完善投委草稿的待核实事项", project_id=p3, status="待办", priority="中",
               owner="模拟研究员丙", due=day(5), description="[模拟] 披露现金转换、客户集中度与融资约束，避免把模型作为事实结论。", meeting_id=""),
        record("demo-task-pilot", title="[模拟] 确认中试与商业验证边界", project_id=p4, status="待办", priority="低",
               owner="模拟研究员甲", due=day(7), description="[模拟] 验证 20 MWh 计划的状态；未取得商业验收前不写成出货。", meeting_id=""),
    ]
    by_id = {document["id"]: document for document in documents}

    def source_line(document_id: str, phrase: str) -> str:
        return next(line for line in by_id[document_id]["content"].splitlines() if phrase in line)

    notes = [
        record("demo-note-income", title="[模拟] 240 / 218 收入差异仍需桥接", project_id=p1, status="待核实",
               document_id="demo-source-beichen-ledger",
               source_quote=source_line("demo-source-beichen-ledger", "22 百万元差异"),
               body=_sim("预测与管理账存在数字差异，但时间及计量范围需先对齐，不能据此断言造假或下滑。",
                         "关联核对收入任务；需核验未验收项目及代理代采净额调整。")),
        record("demo-note-capacity", title="[模拟] 暂不采用“8,000 卡已经上线”", project_id=p2, status="暂不采用",
               document_id="demo-source-yuanshan-operations",
               source_quote=source_line("demo-source-yuanshan-operations", "并非相同时间"),
               body=_sim("8,000 卡是未来规划，4,200 卡是当前已安装，3,000 卡是在租；不能混用。",
                         "暂不采用把规划写成存量的表述，不代表已核实全部运营数据。")),
        record("demo-note-margin", title="[模拟] 毛利率 33% / 21% 需成本桥接", project_id=p2, status="待核实",
               document_id="demo-source-yuanshan-operations",
               source_quote=source_line("demo-source-yuanshan-operations", "毛利率示例为 21%"),
               body=_sim("两份资料是否含电力及机房成本不同，当前证据不支持毛利率下滑结论。",
                         "关联取得含电力成本毛利桥接任务，等待成本明细。")),
        record("demo-note-arithmetic", title="[模拟] 仅核实 EV 示例算术：320 × 20% × 8 = 512", project_id=p3, status="已核实",
               document_id="demo-source-chengchuan-committee",
               source_quote=source_line("demo-source-chengchuan-committee", "进入 EV 为 512"),
               body=_sim("已核实仅表示合成资料内部算术一致；不表示企业业绩、估值合理性或尽调结论已核实。",
                         "模型仍需披露税前、现金转换、无中间分红与融资约束简化。")),
    ]
    deliverables = [
        record("demo-deliverable-beichen", title="北辰机器人｜研究简报草稿（合成）", project_id=p1, kind="研究简报",
               body=_sim("# 北辰机器人研究简报草稿（全部合成，非投资结论）",
                         "## 证据摘录与口径",
                         f"管理层预测资料：{previous_year} 年收入 240 百万元，含未最终验收及代理代采。来源：demo-source-beichen-plan，第 1 段。",
                         f"未审管理账资料：{previous_year} 年收入 218 百万元，不含未最终验收且代采按净额。来源：demo-source-beichen-ledger，第 1 段。",
                         "## 待核实",
                         "22 百万元差异尚无完整桥接；不得直接解释为经营恶化、虚假记载或已验证事实。",
                         "## 推进任务",
                         "核对收入范围与验收政策；抽样访谈客户；补充客户验收证据。负责人和日期见关联任务。")),
        record("demo-deliverable-yuanshan", title="远山算力｜会议纪要草稿（合成）", project_id=p2, kind="会议纪要",
               body=_sim("# 远山算力会议纪要草稿（全部合成，待人工确认）",
                         f"会议日期：{day(-2)}；来源：demo-meeting-yuanshan。",
                         "## 原文摘录",
                         "“8,000 是未来规划，4,200 是当前已安装，不能当作同口径冲突。”",
                         "“33% 与 21% 是否可桥接仍需原始成本明细，不能直接解释为毛利恶化。”",
                         "## 已确认任务示例",
                         f"模拟研究员乙：区分规划、安装、验收与在租卡数；截止 {day(0)}。",
                         f"模拟研究员丙：取得含电力成本的毛利桥接；截止 {day(3)}。",
                         "未形成投资结论；任务示例仅用于演示关联，不向外部发送或自动承诺。")),
    ]
    return {"projects": projects, "tasks": tasks, "documents": documents,
            "meetings": meetings, "notes": notes, "deliverables": deliverables, "activity": []}
