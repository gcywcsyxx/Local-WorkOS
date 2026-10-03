/* Dependency-free, deliberately small Markdown subset. Raw HTML is always text.
 * Work budget, nesting, input/line/table limits fall back to literal text, not truncation.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.WorkOSMarkdown = api;
}(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  var TICK = String.fromCharCode(96);
  function esc(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function plain(s) { return '<pre>' + esc(s) + '</pre>'; }
  function safeURL(s) {
    if (!/^https?:\/\//i.test(s) || /[\s\x00-\x1f\x7f<>"'\\]/.test(s)) return false;
    try { var u = new URL(s); return /^(http:|https:)$/.test(u.protocol) && !!u.hostname; }
    catch (_) { return false; }
  }
  function inline(s, depth, budget) {
    if (s.length > 16384 || depth > 4) return esc(s);
    var out = [], i = 0;
    function find(token, from) {
      var span = Math.min(4096, s.length - from, budget.left);
      if (span <= 0) return -1;
      budget.left -= span;
      var n = s.slice(from, from + span).indexOf(token);
      return n < 0 ? -1 : from + n;
    }
    while (i < s.length) {
      var c = s[i], end, size, marker;
      if (c === '\\' && i + 1 < s.length && '\\*_[]()'.indexOf(s[i + 1]) >= 0) {
        out.push(esc(s[i + 1])); i += 2; continue;
      }
      if (c === TICK) {
        size = 1; while (s[i + size] === TICK) size++;
        marker = s.slice(i, i + size); end = find(marker, i + size);
        if (end >= 0) { out.push('<code>' + esc(s.slice(i + size, end)) + '</code>'); i = end + size; }
        else { out.push(esc(marker)); i += size; }
        continue;
      }
      if (c === '[' || (c === '!' && s[i + 1] === '[')) {
        var image = c === '!', start = i + (image ? 2 : 1), close = find(']', start);
        if (close >= 0 && s[close + 1] === '(' && (end = find(')', close + 2)) >= 0) {
          var label = s.slice(start, close), url = s.slice(close + 2, end);
          if (!image && label.indexOf('[') < 0 && safeURL(url)) {
            out.push('<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(label) + '</a>');
          } else out.push(esc(s.slice(i, end + 1)));
          i = end + 1; continue;
        }
      }
      if (c === '*' || c === '_') {
        size = s[i + 1] === c ? 2 : 1; marker = s.slice(i, i + size);
        var next = s[i + size], prev = i ? s[i - 1] : '';
        if (next && !/\s/.test(next) && !(c === '_' && /[a-zA-Z0-9]/.test(prev))) {
          end = find(marker, i + size);
          if (end > i + size && !/\s/.test(s[end - 1]) && !(c === '_' && /[a-zA-Z0-9]/.test(s[end + size] || ''))) {
            var tag = size === 2 ? 'strong' : 'em';
            out.push('<' + tag + '>' + inline(s.slice(i + size, end), depth + 1, budget) + '</' + tag + '>');
            i = end + size; continue;
          }
        }
        out.push(esc(marker)); i += size; continue;
      }
      out.push(esc(c)); i++;
    }
    return out.join('');
  }
  function render(value) {
    var text = value == null ? '' : String(value);
    if (text.length > 1024 * 1024) return plain(text);
    var lines = text.replace(/\r\n?/g, '\n').split('\n'), out = [], i = 0;
    var budget = { left: Math.max(4096, text.length * 12) };
    function fmt(s) { return inline(s, 0, budget); }
    function cells(s) {
      s = s.trim();
      if (s[0] === '|') s = s.slice(1);
      if (s[s.length - 1] === '|') s = s.slice(0, -1);
      // Sentinel extra columns trigger lossless raw-table fallback; never allocate unbounded cells.
      return s.split('|', 34).map(function (c) { return c.trim(); });
    }
    function separator(s) {
      return !!s && s.length <= 16384 && s.indexOf('|') >= 0 && cells(s).every(function (c) { return /^:?-{3,}:?$/.test(c); });
    }
    function fence(s) { return /^ {0,3}(\x60{3,}|~{3,})(.*)$/.exec(s); }
    function list(s) { return /^ {0,3}(?:([-+*])\s+|([0-9]{1,9})[.)]\s+)(.*)$/.exec(s); }
    function special(n) {
      var s = lines[n] || '';
      return !s.trim() || fence(s) || /^ {0,3}#{1,6}\s+/.test(s) || /^ {0,3}> ?/.test(s) || list(s) ||
        (s.indexOf('|') >= 0 && separator(lines[n + 1]));
    }
    while (i < lines.length) {
      var line = lines[i], m, j;
      if (!line.trim()) { i++; continue; }
      m = fence(line);
      if (m) {
        j = i + 1;
        var marker = m[1], closing = new RegExp('^ {0,3}' + marker[0] + '{' + marker.length + ',}\\s*$');
        while (j < lines.length && !closing.test(lines[j])) j++;
        if (j === lines.length) out.push(plain(lines.slice(i).join('\n')));
        else out.push('<pre><code>' + esc(lines.slice(i + 1, j).join('\n')) + '</code></pre>');
        i = j === lines.length ? j : j + 1; continue;
      }
      if (line.indexOf('|') >= 0 && separator(lines[i + 1])) {
        j = i + 2;
        while (j < lines.length && lines[j].trim() && lines[j].indexOf('|') >= 0) j++;
        var raw = lines.slice(i, j), rows = [cells(line)].concat(lines.slice(i + 2, j).map(cells)), width = rows[0].length;
        if (width > 32 || cells(lines[i + 1]).length !== width || rows.some(function (r) { return r.length !== width; }) ||
            raw.some(function (s) { return s.length > 16384; })) out.push(plain(raw.join('\n')));
        else {
          out.push('<table><thead><tr>' + rows[0].map(function (s) { return '<th>' + fmt(s) + '</th>'; }).join('') + '</tr></thead><tbody>');
          rows.slice(1).forEach(function (r) { out.push('<tr>' + r.map(function (s) { return '<td>' + fmt(s) + '</td>'; }).join('') + '</tr>'); });
          out.push('</tbody></table>');
        }
        i = j; continue;
      }
      m = /^ {0,3}(#{1,6})\s+(.*)$/.exec(line);
      if (m) { out.push('<h' + m[1].length + '>' + fmt(m[2]) + '</h' + m[1].length + '>'); i++; continue; }
      if (/^ {0,3}> ?/.test(line)) {
        var quote = [];
        while (i < lines.length && /^ {0,3}> ?/.test(lines[i])) quote.push(fmt(lines[i++].replace(/^ {0,3}> ?/, '')));
        out.push('<blockquote><p>' + quote.join('<br>') + '</p></blockquote>'); continue;
      }
      m = list(line);
      if (m) {
        var ordered = !!m[2], tag = ordered ? 'ol' : 'ul';
        out.push('<' + tag + (ordered ? ' start="' + Number(m[2]) + '"' : '') + '>');
        while (i < lines.length && (m = list(lines[i])) && !!m[2] === ordered) {
          out.push('<li' + (ordered ? ' value="' + Number(m[2]) + '"' : '') + '>' + fmt(m[3]) + '</li>'); i++;
        }
        out.push('</' + tag + '>'); continue;
      }
      var paragraph = [fmt(line)]; i++;
      while (i < lines.length && !special(i)) paragraph.push(fmt(lines[i++]));
      out.push('<p>' + paragraph.join('<br>') + '</p>');
    }
    return out.join('\n');
  }
  return Object.freeze({ render: render });
}));
