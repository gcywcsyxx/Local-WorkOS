'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { performance } = require('node:perf_hooks');
const { render } = require('../web/markdown.js');
let count = 0;
function test(name, fn) { fn(); count++; console.log('ok - ' + name); }
function escape(s) { return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function visible(html) {
  return html.replace(/<br>/g, '\n').replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
}
test('browser and CommonJS APIs agree; no DOM needed', () => {
  const context = { window: {}, URL };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/markdown.js'), 'utf8'), context);
  assert.equal(typeof context.window.WorkOSMarkdown.render, 'function');
  assert.equal(context.window.WorkOSMarkdown.render('# 中文'), render('# 中文'));
  assert.equal(render(null), ''); assert.equal(render(undefined), '');
  assert.equal(render(123), '<p>123</p>');
});
test('Chinese headings, paragraphs, emphasis, bold and numbers', () => {
  const html = render('# 中国研究 2026\n\n收入 **增长30%**，*谨慎*，_英文_。\n第二行 123.45');
  assert.match(html, /<h1>中国研究 2026<\/h1>/);
  assert.match(html, /<strong>增长30%<\/strong>/);
  assert.match(html, /<em>谨慎<\/em>/);
  assert.match(html, /<em>英文<\/em>/);
  assert.match(html, /<br>第二行 123\.45/);
  for (let n = 1; n <= 6; n++) assert.equal(render('#'.repeat(n) + ' 中文'), '<h' + n + '>中文</h' + n + '>');
});
test('bullet and ordered lists retain nonsequential numeric values', () => {
  const html = render('- 收入\n* **利润**\n+ 现金\n\n3. 第一\n9) 第二');
  assert.match(html, /<ul>/); assert.match(html, /<li><strong>利润<\/strong><\/li>/);
  assert.match(html, /<ol start="3">/); assert.match(html, /<li value="9">第二<\/li>/);
});
test('simple tables preserve Chinese, numbers, source labels and formatting', () => {
  const html = render('| 项目 | 收入 | 来源 |\n| :--- | ---: | --- |\n| **中国** | 123.45 | [S1] |\n| 海外 | 99 | [S2] |');
  assert.match(html, /<table><thead>/); assert.match(html, /<th>项目<\/th>/);
  assert.match(html, /<td><strong>中国<\/strong><\/td>/);
  assert.match(html, /<td>123\.45<\/td>/); assert.match(html, /<td>\[S1\]<\/td>/);
});
test('block quotes and code remain inert', () => {
  const tick = String.fromCharCode(96);
  const html = render('> 引用 **中文** [S1]\n> 第二行\n\n' + tick.repeat(3) + 'js\n<img src=x onerror="alert(1)">\n**原样**\n' + tick.repeat(3) + '\n\n' + tick + 'a < b && "x"' + tick);
  assert.match(html, /<blockquote><p>引用 <strong>中文<\/strong> \[S1\]<br>第二行/);
  assert.match(html, /<pre><code>&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;\n\*\*原样\*\*<\/code><\/pre>/);
  assert.match(html, /<code>a &lt; b &amp;&amp; &quot;x&quot;<\/code>/);
  assert.equal(render('~~~\n中文\n~~~~'), '<pre><code>中文</code></pre>');
});
test('source labels do not eat following links', () => {
  const html = render('[S1] [S20] 来源 [官网](https://example.com/a?q=中国&n=2)');
  assert.ok(html.includes('[S1] [S20] 来源 '));
  assert.match(html, /href="https:\/\/example\.com\/a\?q=中国&amp;n=2"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(render('[普通](http://example.com)'), /<a /);
});
test('all raw HTML and quote/ampersand content is escaped', () => {
  const raw = '<script>alert(1)</script><svg onload="x"><img src=x onerror=\'x\'></svg> & "引号" \'单引号\'';
  assert.equal(render(raw), '<p>' + escape(raw) + '</p>');
  assert.equal(visible(render(raw)), raw);
  assert.ok(!render(raw).includes('<script')); assert.ok(!render(raw).includes('<img'));
});
test('unsafe schemes, protocol-relative URLs and attribute injection stay visible', () => {
  for (const url of ['javascript:alert(1)', 'JaVaScRiPt:x', 'data:text/html,<svg/onload=x>', 'vbscript:x', '//example.com', '/relative', 'https://x/"onmouseover="x', "https://x/'onclick='x", 'https://x/ onerror=x', 'https://x/\tonload=x', 'https:\\example.com', 'https://']) {
    const raw = '[标签](' + url + ')', html = render(raw);
    assert.ok(!html.includes('<a '), url); assert.equal(visible(html), raw, url);
  }
  const raw = '[<img onerror="x">](https://example.com/?x=&quot;onmouseover=evil)';
  const html = render(raw);
  assert.match(html, /&lt;img onerror=&quot;x&quot;&gt;/);
  assert.ok(!html.includes('<img'));
  assert.match(html, /&amp;quot;/);
});
test('Markdown images are literal, never images or linked images', () => {
  for (const raw of ['![图](https://example.com/x.png)', '![图](data:image/svg+xml,x)', '![破损](javascript:x)']) {
    assert.equal(visible(render(raw)), raw); assert.ok(!/<(?:img|a)\b/.test(render(raw)));
  }
});
test('literal arithmetic, underscores and unmatched syntax preserve content', () => {
  for (const raw of ['2 * 3 + 4 * 5 = 26', 'a_b_c', '**未闭合', '* 开头?\n尾部 **未闭合', '[S1]', '[缺失](https://example.com', '[broken', '尾部 \\', '##无空格', '| 中国 | 1 |\n| -- | -- |']) {
    // List markers are structural; exclude that separate fixture from literal equality.
    if (!raw.startsWith('* ')) assert.equal(visible(render(raw)), raw);
    else assert.ok(visible(render(raw)).includes('尾部 **未闭合'));
  }
  assert.equal(render('2 * 3 + 4 * 5'), '<p>2 * 3 + 4 * 5</p>');
});
test('unclosed code fence and malformed table never discard data', () => {
  const raw = String.fromCharCode(96).repeat(3) + 'python\n<中文>\n末尾 [S1]';
  assert.equal(render(raw), '<pre>' + escape(raw) + '</pre>');
  const table = '| A | B |\n| --- | --- |\n| 1 | 2 | 3 |';
  assert.equal(render(table), '<pre>' + table + '</pre>');
});
test('wide and long tables fall back losslessly', () => {
  const header = Array.from({length: 100}, (_, i) => '列' + i).join('|');
  const raw = header + '\n' + Array(100).fill('---').join('|') + '\n' + Array.from({length: 100}, (_, i) => '值' + i).join('|');
  assert.equal(render(raw), '<pre>' + raw + '</pre>');
  const long = '| A | B |\n| --- | --- |\n| ' + '中'.repeat(20000) + ' | END |';
  assert.equal(render(long), '<pre>' + long + '</pre>');
});
test('oversized input and pathological inline scans are bounded and lossless', () => {
  const raw = '**' + '<中>&'.repeat(300000) + 'END';
  let start = performance.now();
  assert.equal(render(raw), '<pre>' + escape(raw) + '</pre>');
  const adversarial = Array(60).fill('[x '.repeat(4000) + 'END').join('\n');
  assert.ok(render(adversarial).includes('END'));
  assert.ok(performance.now() - start < 10000, 'bounded rendering within generous 10s budget');
  const line = '**' + '中'.repeat(20000) + 'TAIL';
  assert.equal(render(line), '<p>' + line + '</p>');
});
test('CRLF and nested-looking constructs stay safe', () => {
  assert.equal(render('# 中文\r\n\r\n正文'), '<h1>中文</h1>\n<p>正文</p>');
  const raw = '> '.repeat(10000) + '<img onerror=x>';
  assert.ok(!render(raw).includes('<img'));
  const html = render('**粗体与 _强调_**');
  assert.match(html, /<strong>粗体与 <em>强调<\/em><\/strong>/);
});
console.log(count + ' Markdown test groups passed');
