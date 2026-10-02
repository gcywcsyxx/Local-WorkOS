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
 import io,json
 from openpyxl import Workbook
 from openpyxl.styles import Font,PatternFill,Alignment
 wb=Workbook();summary=wb.active;summary.title='Summary'
 summary.append(['Local WorkOS Valuation Model']);summary.append(['Method',result.get('method_label',method)]);summary.append(['Currency / Unit',str(assumptions.get('currency',''))+' / '+str(assumptions.get('unit',''))]);summary.append(['Formula',result.get('formula','')]);summary.append([]);summary.append(['Metric','Value'])
 for key in ('equity_value','enterprise_value','implied_value_per_share','irr','moic','entry_sponsor_equity','sponsor_proceeds'):
  if key in result:summary.append([key,result[key]])
 for cell in summary[1]:cell.font=Font(name='Arial',bold=True,size=14,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17365D')
 for row in summary.iter_rows(min_row=2):
  for cell in row:cell.font=Font(name='Arial',size=10)
 summary.column_dimensions['A'].width=28;summary.column_dimensions['B'].width=54
 ass=wb.create_sheet('Assumptions');ass.append(['Assumption','Value'])
 forecasts=assumptions.get('forecasts')
 for k,v in assumptions.items():
  if k!='forecasts':ass.append([k,json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v])
 if isinstance(forecasts,list):
  forecast=wb.create_sheet('Forecasts');keys=sorted({k for row in forecasts if isinstance(row,dict) for k in row});forecast.append(keys)
  for item in forecasts:
   if isinstance(item,dict):forecast.append([item.get(k) for k in keys])
  for col in forecast.columns:
   letter=col[0].column_letter;forecast.column_dimensions[letter].width=18
 rows=result.get('forecast') or result.get('rows')
 if isinstance(rows,list):
  ws=wb.create_sheet('Calculated Output');keys=sorted({k for row in rows if isinstance(row,dict) for k in row});ws.append(keys)
  for row in rows:
   if isinstance(row,dict):ws.append([row.get(k) for k in keys])
 for ws in wb.worksheets:
  ws.freeze_panes='A2';ws.sheet_view.showGridLines=False
  for cell in ws[1]:cell.font=Font(name='Arial',bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17365D');cell.alignment=Alignment(wrap_text=True)
  for row in ws.iter_rows():
   for cell in row:
    if cell.value is not None:cell.font=Font(name='Arial',size=10,bold=cell.row==1,color='FFFFFF' if cell.row==1 else '243345');cell.alignment=Alignment(vertical='top',wrap_text=True)
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
