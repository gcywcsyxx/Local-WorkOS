"""Strict data blocks for editable slide export; no execution or invented data."""
import json
import math
import re

def parse_blocks(body):
    lines=body.splitlines();blocks=[];heading="核心内容";pending=[];i=0
    def flush():
        if pending:blocks.append({"kind":"text","heading":heading,"items":list(pending)});pending.clear()
    while i<len(lines):
        line=lines[i].strip()
        if line.startswith("```chart"):
            flush();i+=1;raw=[]
            while i<len(lines) and lines[i].strip()!="```":raw.append(lines[i]);i+=1
            if i>=len(lines):raise ValueError("图表数据块缺少结束标记")
            try:data=json.loads("\n".join(raw))
            except (ValueError,TypeError) as e:raise ValueError("图表必须提供有效JSON数据") from e
            validate_chart(data)
            blocks.append({"kind":"chart","heading":heading,"data":data});i+=1;continue
        if line.startswith("#"):
            flush();heading=line.lstrip("# ").strip() or "内容";i+=1;continue
        if i+1<len(lines) and "|" in line and table_separator(lines[i+1]):
            flush();header=table_cells(line);i+=2;rows=[]
            if not 1<=len(header)<=6:raise ValueError("PPT表格请保持1至6列；超宽表未自动截断")
            while i<len(lines) and "|" in lines[i]:
                row=table_cells(lines[i])
                if len(row)!=len(header):raise ValueError("表格每行列数必须一致")
                if any(len(cell)>160 for cell in row):raise ValueError("单个表格单元格过长，请拆分表述；正文未截断")
                rows.append(row);i+=1
            blocks.append({"kind":"table","heading":heading,"header":header,"rows":rows});continue
        if line:pending.append(line)
        i+=1
    flush()
    return blocks or [{"kind":"text","heading":heading,"items":["暂无正文"]}]

def table_cells(line):return [x.strip() for x in line.strip().strip("|").split("|")]
def table_separator(line):
    cells=table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?",x) for x in cells)

def validate_chart(data):
    if not isinstance(data,dict) or set(data)-{"type","categories","series","title","source"}:raise ValueError("图表字段无效")
    if data.get("type") not in ("column","bar","line"):raise ValueError("仅支持column/bar/line图表")
    categories=data.get("categories");series=data.get("series")
    if not isinstance(categories,list) or not 1<=len(categories)<=30 or any(not isinstance(x,str) or len(x)>80 for x in categories):raise ValueError("图表需1至30个明确分类")
    if not isinstance(series,list) or not 1<=len(series)<=6:raise ValueError("图表需1至6个明确数据系列")
    for item in series:
        if not isinstance(item,dict) or set(item)-{"name","values"} or not isinstance(item.get("name"),str) or len(item["name"])>120:raise ValueError("图表系列名称无效")
        values=item.get("values")
        if not isinstance(values,list) or len(values)!=len(categories):raise ValueError("图表数据数量必须与分类对应")
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in values):raise ValueError("图表仅接受明确的有限数字，不把空值当零")
    for key in ("title","source"):
        if key in data and (not isinstance(data[key],str) or len(data[key])>500):raise ValueError("图表标题或来源无效")
