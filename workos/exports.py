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
