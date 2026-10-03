# Editable PowerPoint export

Deliverables → PPTX exports a local editable deck. No data is sent to a model by the exporter.

## Paragraphs
Markdown headings start sections; long sections continue on additional slides. Source labels in the text stay in the deck.

## Tables
Standard Markdown tables become editable PowerPoint tables; headers repeat on continuation slides. Up to six columns and 160 characters per cell. Wide or malformed tables fail explicitly rather than losing values.

```markdown
# Company comparison
| Company | Revenue (RMBm) | Source |
|---|---:|---|
| Synthetic A | 100 | [S1] |
| Synthetic B | 120 | [S2] |
```

## Charts
Use a fenced `chart` block with explicit data. Types: `column`, `bar`, `line`. There must be 1–30 categories and 1–6 series; every category needs a finite number. Missing values are rejected, not treated as zero. Sources are shown on the slide and preserved in notes.

````markdown
# Revenue trend
```chart
{
  "type": "column",
  "categories": ["2026", "2027"],
  "series": [{"name": "Revenue (RMBm)", "values": [100, 120]}],
  "source": "[S1] Synthetic example; not investment data"
}
```
````

The native chart includes its editable Excel workbook. JSON is parsed as data, never executed. The exporter does not fetch source URLs or infer missing numbers.

## Limits
More than 200 content slides is rejected rather than silently truncated. Exports remain drafts: factual claims, data provenance and final layout require review. This capability does not automatically build a decision-ready IC memo or certify visual layout.
