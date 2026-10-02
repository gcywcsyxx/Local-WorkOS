"""Safe, portable deliverables. Text never becomes executable markup."""
import html
import io
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def markdown(record):
 return '# '+record['title']+'\n\n'+record.get('body','')+'\n\n---\nLocal WorkOS · '+datetime.now().strftime('%Y-%m-%d')+'\n'

def html_report(record):
 title=html.escape(record['title'])
 lines=record.get('body','').splitlines()
 content=[]
 for i,line in enumerate(lines):
  escaped=html.escape(line)
  if line.startswith('## '):content.append(f'<h2 id="s{i}">{html.escape(line[3:])}</h2>')
  elif line.startswith('# '):content.append(f'<h2 id="s{i}">{html.escape(line[2:])}</h2>')
  elif line.strip():content.append(f'<p id="p{i}">{escaped}</p>')
  else:content.append('<div class="gap"></div>')
 report=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f5f7;color:#243345;font:16px/1.65 Arial,"Microsoft YaHei",sans-serif}}main{{max-width:1000px;margin:40px auto;padding:42px 48px;background:white;border:1px solid #dbe1e7;border-radius:12px}}h1{{font-size:30px;color:#153452;margin:0 0 18px}}h2{{font-size:22px;color:#153452;margin:28px 0 10px}}p{{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}}.notice{{padding:14px 18px;background:#fff8df;border:1px solid #d9c994;margin:18px 0}}.gap{{height:8px}}footer{{border-top:1px solid #dde3e9;margin-top:30px;padding-top:16px;color:#667687;font-size:13px}}@media(max-width:700px){{main{{margin:0;padding:70px 22px 80px;border:0;border-radius:0}}h1{{font-size:25px}}}}@media print{{body{{background:white}}main{{margin:0;border:0;padding:0;max-width:none}}p{{break-inside:avoid}}}}
</style></head><body><main id="report"><h1>{title}</h1><div class="notice" id="instructions">工作草稿，结论与数字请复核。默认阅读模式；点击“编辑正文”可改正文并添加批注。“保存 HTML 副本”下载包含修改和批注的独立文件；不回写平台数据库。</div><section id="body">{''.join(content)}</section><footer id="footer">Local WorkOS · {datetime.now().strftime('%Y-%m-%d')} · 请在外发前确认资料范围及敏感信息。</footer></main></body></html>'''
 editor=(ROOT/'web'/'report-editor.js').read_text(encoding='utf-8')
 # Prevent a script terminator even if the independently authored asset changes.
 editor=editor.replace('</', '<\\/')
 editor_css='''<style id="report-editor-style">
 body{padding-right:340px}#report-editor-ui{position:fixed;right:0;top:0;bottom:0;width:320px;overflow:auto;background:#f8fafc;border-left:1px solid #ccd5df;padding:18px;font:14px/1.5 Arial,sans-serif}#report-editor-ui strong,#report-editor-ui label{display:block;margin-bottom:10px}#report-editor-ui button{padding:8px 10px;margin:4px 5px 8px 0;cursor:pointer}#report-editor-ui textarea{width:100%;resize:vertical}#report-selected-quote,.report-note blockquote{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f7;margin:8px 0;padding:8px}.report-note{border-top:1px solid #ccd5df;padding:10px 0}.report-note p{white-space:pre-wrap;overflow-wrap:anywhere}[contenteditable]{outline:1px dashed #8ba2bc;white-space:pre-wrap}h2{white-space:pre-wrap}@media(max-width:900px){body{padding-right:0}#report-editor-ui{position:static;width:auto;border-left:0;border-top:1px solid #ccd5df}}@media print{body{padding-right:0}#report-editor-ui{display:none}}
 </style>'''
 state='<script type="application/json" id="report-notes-data">{"version":1,"notes":[]}</script>'
 return report.replace('</head>',editor_css+'</head>').replace('</body>',state+'<script id="report-editor-script">'+editor+'</script></body>')

def expert_minutes_docx(title,summary,participants='',date_text=''):
 from docx import Document
 from docx.shared import Pt,Cm
 from docx.oxml import OxmlElement
 from docx.oxml.ns import qn
 from io import BytesIO
 doc=Document();section=doc.sections[0];section.page_width=Cm(21);section.page_height=Cm(29.7);section.top_margin=Cm(2.2);section.bottom_margin=Cm(2.2);section.left_margin=Cm(2);section.right_margin=Cm(2)
 normal=doc.styles['Normal'];normal.font.name='Arial';normal.font.size=Pt(10)
 normal.element.rPr.rFonts.set(qn('w:eastAsia'),'KaiTi')
 for name,size in [('Heading 1',14),('Heading 2',11)]:
  style=doc.styles[name];style.font.name='Arial';style.font.size=Pt(size);style.font.bold=True;style.font.color.rgb=None;style.element.rPr.rFonts.set(qn('w:eastAsia'),'KaiTi')
 p=doc.add_paragraph();p.style=doc.styles['Normal'];run=p.add_run(title);run.bold=True;run.font.name='Arial';run.font.size=Pt(14);run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'KaiTi');p.paragraph_format.space_after=Pt(6)
 if date_text:
  p=doc.add_paragraph(date_text);p.paragraph_format.space_after=Pt(4)
 if participants:
  p=doc.add_paragraph(participants);p.paragraph_format.space_after=Pt(8)
 lines=summary.replace('\r\n','\n').replace('\r','\n').split('\n')
 for raw in lines:
  line=raw.strip()
  if not line:
   continue
  if line.startswith('【') and line.endswith('】'):
   doc.add_heading(line.strip('【】'),1)
  elif line.startswith('# '):
   doc.add_heading(line[2:].strip(),1)
  elif line.startswith('## '):
   doc.add_heading(line[3:].strip(),2)
  elif line.startswith('➢'):
   p=doc.add_paragraph(style='Normal');p.paragraph_format.left_indent=Cm(1.25);p.paragraph_format.first_line_indent=Cm(-.35);p.add_run('➢ '+line[1:].strip())
  elif line.startswith('o '):
   p=doc.add_paragraph(style='Normal');p.paragraph_format.left_indent=Cm(.8);p.paragraph_format.first_line_indent=Cm(-.35);p.add_run('o '+line[2:].strip())
  elif line.startswith('• '):
   p=doc.add_paragraph(style='Normal');p.paragraph_format.left_indent=Cm(.4);p.paragraph_format.first_line_indent=Cm(-.35);p.add_run('• '+line[2:].strip())
  elif line.startswith('- '):
   p=doc.add_paragraph(style='Normal');p.paragraph_format.left_indent=Cm(.4);p.paragraph_format.first_line_indent=Cm(-.35);p.add_run('• '+line[2:].strip())
  else:
   doc.add_paragraph(line)
 out=BytesIO();doc.save(out);return out.getvalue()


def valuation_xlsx(method, assumptions, result):
    import io, json
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook(); summary = wb.active; summary.title = "Summary"
    summary.append(["Local WorkOS Valuation Model"]); summary.append(["Method", result.get("method_label", method)]); summary.append(["Currency / Unit", str(assumptions.get("currency", ""))+" / "+str(assumptions.get("unit", ""))]); summary.append(["Formula", result.get("formula", "")]); summary.append([]); summary.append(["Metric", "Value / Formula"])
    ass = wb.create_sheet("Assumptions"); ass.append(["Assumption", "Input"])
    for key, value in assumptions.items():
        if key != "forecasts": ass.append([key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict,list)) else value])
    ass.freeze_panes="A2"; ass.column_dimensions["A"].width=30; ass.column_dimensions["B"].width=28
    def ref(key):
        row = next((r for r in range(2, ass.max_row+1) if ass.cell(r,1).value == key), None)
        return "Assumptions!$B$" + str(row) if row else "0"
    if method in ("net_income", "ps"):
        input_key = "net_income" if method == "net_income" else "revenue"; multiple_key = "pe_multiple" if method == "net_income" else "ps_multiple"
        summary.append(["Equity Value", "="+ref(input_key)+"*"+ref(multiple_key)])
        if assumptions.get("diluted_shares"): summary.append(["Implied Value / Share", "=B7/"+ref("diluted_shares")])
    elif method == "dcf":
        forecasts = assumptions.get("forecasts") or []; ws = wb.create_sheet("DCF_Forecast")
        ws.append(["Year","EBIT","Tax Rate","Cash Tax","NOPAT","D&A","CapEx","ΔNWC","FCFF","Discount Period","Discount Factor","PV FCFF"])
        for idx, row in enumerate(forecasts, 2):
            ebit = row.get("ebit") if row.get("ebit") is not None else row.get("revenue",0)*row.get("ebit_margin",0)
            tax = row.get("tax_rate") if row.get("tax_rate") is not None else assumptions.get("tax_rate",0)
            period = idx-1 if assumptions.get("discount_timing") == "year_end" else idx-1.5
            ws.append([row.get("year"), ebit, tax, "=MAX(0,B%d)*C%d"%(idx,idx), "=B%d-D%d"%(idx,idx), row.get("da"), row.get("capex"), row.get("delta_nwc"), "=E%d+F%d-G%d-H%d"%(idx,idx,idx,idx), period, "=1/(1+%s)^J%d"%(ref("wacc"),idx), "=I%d*K%d"%(idx,idx)])
        if forecasts:
            n = len(forecasts)+1; last = n; tvrow = n+3
            if assumptions.get("terminal_method") == "perpetuity": terminal = "=I%d*(1+%s)/(%s-%s)"%(last,ref("terminal_growth"),ref("wacc"),ref("terminal_growth"))
            else: terminal = "="+str(result.get("terminal_value",0))
            ws.cell(tvrow,1,"Terminal Value"); ws.cell(tvrow,2,terminal); ws.cell(tvrow+1,1,"PV Terminal"); ws.cell(tvrow+1,2,"=B%d/(1+%s)^J%d"%(tvrow,ref("wacc"),last))
            evrow = summary.max_row+1; summary.append(["Enterprise Value", "=SUM(DCF_Forecast!L2:L%d)+DCF_Forecast!B%d"%(n,tvrow+1)]); summary.append(["Equity Value", "=B%d-%s-%s"%(evrow,ref("net_debt"),ref("minority_interest"))])
        ws.freeze_panes="A2"
        for col, width in enumerate((16,16,14,16,16,14,14,14,16,18,18,18),1): ws.column_dimensions[get_column_letter(col)].width=width
    elif method == "lbo":
        forecasts = assumptions.get("forecasts") or []; ws = wb.create_sheet("LBO_Model")
        ws.append(["Period","EBITDA","D&A","CapEx","ΔNWC","Tax Rate","Interest Rate","Mandatory Amort.","Cash Sweep %","Opening Debt","Opening Cash","Interest","Tax","Cash Before Debt","Mandatory Due","Mandatory Paid","Sweep","Ending Debt","Ending Cash","Funding Gap"])
        for idx, row in enumerate(forecasts,2):
            vals = [row.get("year"),row.get("ebitda"),row.get("da"),row.get("capex"),row.get("delta_nwc"),row.get("tax_rate",assumptions.get("tax_rate")),row.get("interest_rate",assumptions.get("interest_rate")),row.get("mandatory_amortization",assumptions.get("mandatory_amortization")),row.get("cash_sweep_pct",assumptions.get("cash_sweep_pct"))]
            f = ["="+ref("entry_debt") if idx==2 else "=R%d"%(idx-1), "="+ref("initial_cash") if idx==2 else "=S%d"%(idx-1), "=J%d*G%d"%(idx,idx), "=MAX(0,B%d-C%d-L%d)*F%d"%(idx,idx,idx,idx), "=B%d-M%d-L%d-D%d-E%d"%(idx,idx,idx,idx,idx), "=MIN(J%d,H%d)"%(idx,idx), "=MIN(O%d,MAX(0,K%d+N%d))"%(idx,idx,idx), "=IF(K%d+N%d-P%d>0,MIN(MAX(0,J%d-P%d),(K%d+N%d-P%d)*I%d),0)"%(idx,idx,idx,idx,idx,idx,idx,idx,idx), "=MAX(0,J%d-P%d-Q%d)"%(idx,idx,idx), "=MAX(0,K%d+N%d-P%d-Q%d)"%(idx,idx,idx,idx), "=MAX(0,-(K%d+N%d-P%d))+O%d-P%d"%(idx,idx,idx,idx,idx)]
            ws.append(vals+f)
        ws.freeze_panes="A2"
        if forecasts:
            n = len(forecasts)+1
            for col,label in enumerate(("Opening Debt","Opening Cash","Interest","Tax","Cash Before Debt","Mandatory Due","Mandatory Paid","Sweep","Ending Debt","Ending Cash","Funding Gap"),10): ws.cell(1,col,label)
            er=n+2; ws.cell(er,1,"Formula Exit EV"); ws.cell(er,2,"=B%d*%s"%(n,str(assumptions.get("exit_multiple",0))))
            pr=n+3; ws.cell(pr,1,"Formula Sponsor Proceeds"); ws.cell(pr,2,"=MAX(0,B%d-R%d+S%d-%s)"%(er,n,n,str(assumptions.get("exit_fees",0))))
            sr=n+4; ws.cell(sr,1,"Formula Sponsor Equity"); ws.cell(sr,2,"="+ref("entry_ev")+"+"+ref("entry_fees")+"+"+ref("minimum_cash")+"-"+ref("entry_debt")+"-"+ref("seller_rollover"))
            mr=n+5; ws.cell(mr,1,"Formula MOIC"); ws.cell(mr,2,"=B%d/B%d"%(pr,sr))
            from datetime import date as _date
            ws.cell(n+6,1,"Entry Date"); ws.cell(n+6,2,_date.fromisoformat(assumptions["entry_date"]))
            ws.cell(n+7,1,"Exit Date"); ws.cell(n+7,2,_date.fromisoformat(assumptions["exit_date"]))
            ws.cell(n+8,1,"Formula IRR"); ws.cell(n+8,2,"=B%d^(365/(B%d-B%d))-1"%(mr,n+7,n+6))
            ws.cell(n+10,1,"Python Ground Truth — Sponsor Proceeds"); ws.cell(n+10,2,result.get("sponsor_proceeds")); ws.cell(n+11,1,"Python Ground Truth — IRR"); ws.cell(n+11,2,result.get("irr"))
        for col in range(1,21): ws.column_dimensions[get_column_letter(col)].width=16
    rows = result.get("forecast") or result.get("rows")
    if isinstance(rows, list):
        output=wb.create_sheet("Calculated_Output"); keys=sorted({k for row in rows if isinstance(row,dict) for k in row}); output.append(keys)
        for row in rows:
            if isinstance(row,dict): output.append([row.get(k) for k in keys])
    for key in ("equity_value","enterprise_value","implied_value_per_share","irr","moic","entry_sponsor_equity","sponsor_proceeds"):
        if key in result and not any(summary.cell(r,1).value in ("Equity Value","Enterprise Value","Implied Value / Share") for r in range(7,summary.max_row+1)): summary.append([key,result[key]])
    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines=False
        if sheet.max_row: sheet.freeze_panes=sheet.freeze_panes or "A2"
        for cell in sheet[1]: cell.font=Font(name="Arial",bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="17365D"); cell.alignment=Alignment(wrap_text=True)
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    cell.font=Font(name="Arial",size=10,bold=cell.row==1,color="FFFFFF" if cell.row==1 else "243345")
                    cell.alignment=Alignment(vertical="top",wrap_text=True)
    out=io.BytesIO();wb.save(out);return out.getvalue()

def docx_report(record):
 try:
  from docx import Document
  from docx.shared import Pt,Cm,RGBColor
  from docx.oxml import OxmlElement
  from docx.oxml.ns import qn
 except ImportError as exc:raise ValueError('本机缺少 python-docx，请先安装可选文档依赖') from exc
 doc=Document()
 section=doc.sections[0];section.top_margin=Cm(1.8);section.bottom_margin=Cm(1.8);section.left_margin=Cm(2);section.right_margin=Cm(2)
 normal=doc.styles['Normal'];normal.font.name='Arial';normal.font.size=Pt(10.5)
 normal.element.rPr.rFonts.set(qn('w:eastAsia'),'KaiTi')
 doc.add_heading(record['title'],0)
 for line in record.get('body','').splitlines():
  if line.startswith('#'):doc.add_heading(line.lstrip('# ').strip(),min(len(line)-len(line.lstrip('#')),3))
  else:doc.add_paragraph(line)
 doc.add_paragraph('工作草稿，请复核来源、数字和外发范围。')
 out=io.BytesIO();doc.save(out);return out.getvalue()
