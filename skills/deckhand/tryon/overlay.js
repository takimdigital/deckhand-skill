/**
 * Deckhand try-on overlay — injected by the local helper into the owner's dev site (never prod).
 * Pick any element -> choose what it is -> N real, licensed variants appear IN the page, wearing the
 * site's colours and the owner's own words -> ←/→ to compare (instant, client-side) -> Keep / Discard.
 * No licensed design fits (or the owner wants another)? "Ask AI to draft one": the agent writes it once,
 * the engine gates it, and it appears here labelled AI-generated.
 * The page is never edited here: the helper writes source, the dev server's HMR re-renders.
 */
(function () {
  if (window.__DH_TRYON__) return;
  window.__DH_TRYON__ = true;
  var me = document.querySelector('script[data-dh-token]');
  var TOKEN = me ? me.getAttribute('data-dh-token') : '';
  var SS = 'dh-tryon-state';

  /* ------------------------------------------------------------ api */
  function api(name, body) {
    return fetch('/__dh/api/' + name, {
      method: body ? 'POST' : 'GET',
      headers: { 'content-type': 'application/json', 'x-dh-token': TOKEN },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) { return r.json(); });
  }

  /* ------------------------------------------------------------ ui shell */
  var host = document.createElement('div');
  host.setAttribute('data-dh-ui', '');
  host.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483646';
  var root = host.attachShadow({ mode: 'open' });
  root.innerHTML = '<style>' + [
    ':host{all:initial}*{box-sizing:border-box;font:13px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}',
    '.pill{pointer-events:auto;position:fixed;right:18px;bottom:18px;display:flex;align-items:center;gap:8px;padding:9px 14px;border-radius:999px;background:rgba(17,17,19,.92);color:#fff;cursor:pointer;box-shadow:0 8px 30px rgba(0,0,0,.28);user-select:none;border:1px solid rgba(255,255,255,.08)}',
    '.pill b{font-weight:600;letter-spacing:.2px}.pill.on{background:#2563eb}',
    '.dot{width:7px;height:7px;border-radius:50%;background:#34d399}',
    '.outline{position:fixed;pointer-events:none;border:2px solid #2563eb;border-radius:6px;background:rgba(37,99,235,.06);transition:all .05s}',
    '.tag{position:fixed;pointer-events:none;background:#111;color:#fff;border-radius:6px;padding:3px 8px;font-size:12px;white-space:nowrap;max-width:70vw;overflow:hidden;text-overflow:ellipsis}',
    '.panel{pointer-events:auto;position:fixed;right:18px;bottom:70px;width:380px;max-height:70vh;overflow:auto;background:#fff;color:#18181b;border:1px solid #e4e4e7;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.22);padding:14px}',
    '.h{font-weight:600;font-size:14px;margin:0 0 8px}.muted{color:#71717a}.small{font-size:12px}',
    '.crumb{display:flex;gap:8px;align-items:flex-start;padding:6px 8px;border-radius:8px;cursor:pointer}.crumb:hover{background:#f4f4f5}.crumb.sel{background:#eff6ff}',
    '.crumb code{font:12px ui-monospace,monospace;color:#52525b}',
    'select,button{font:inherit;border:1px solid #d4d4d8;border-radius:8px;padding:6px 10px;background:#fff;color:#18181b;cursor:pointer}',
    'button.primary{background:#18181b;color:#fff;border-color:#18181b}button.blue{background:#2563eb;color:#fff;border-color:#2563eb}',
    'button[disabled]{opacity:.45;cursor:not-allowed}.row{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}',
    '.err{margin-top:10px;padding:8px 10px;border-radius:8px;background:#fef2f2;color:#991b1b;white-space:pre-wrap;font-size:12px}',
    '.ok{margin-top:10px;padding:8px 10px;border-radius:8px;background:#ecfdf5;color:#065f46;font-size:12px}',
    '.bar{pointer-events:auto;position:fixed;left:50%;bottom:18px;transform:translateX(-50%);display:flex;align-items:center;gap:10px;padding:8px 10px 8px 14px;border-radius:14px;background:rgba(17,17,19,.94);color:#fff;box-shadow:0 12px 40px rgba(0,0,0,.35);max-width:min(920px,calc(100vw - 24px))}',
    '.bar button{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.14);color:#fff;padding:6px 10px;white-space:nowrap;flex:none}',
    '.bar button.keep{background:#16a34a;border-color:#16a34a}.bar .meta{display:flex;flex-direction:column;min-width:0}',
    '.bar .name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bar .sub{font-size:11.5px;color:#a1a1aa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.fit{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;margin-left:6px}.fit.g{background:#14532d;color:#bbf7d0}.fit.y{background:#713f12;color:#fde68a}',
    '.count{font-variant-numeric:tabular-nums;color:#d4d4d8;min-width:44px;text-align:center}',
    '.fit.ai{background:#4c1d95;color:#ede9fe}.ai-box{margin-top:10px;padding:10px;border-radius:10px;background:#f5f3ff;border:1px solid #ddd6fe;color:#3b0764;font-size:12px}',
    'textarea{font:inherit;width:100%;min-height:54px;border:1px solid #d4d4d8;border-radius:8px;padding:6px 8px;resize:vertical;margin-top:6px}',
    'button.ai{background:#6d28d9;color:#fff;border-color:#6d28d9}.bar button.ai{background:#6d28d9;border-color:#6d28d9}',
    'code.say{display:block;margin-top:6px;padding:6px 8px;border-radius:6px;background:#ede9fe;color:#3b0764;font:12px ui-monospace,monospace;white-space:pre-wrap}',
    '.tabs{display:flex;gap:4px;margin:0 0 10px;padding:3px;border-radius:10px;background:#f4f4f5}.tabs button{flex:1;border:0;background:transparent;padding:5px 8px}.tabs button.on{background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.12);font-weight:600}',
    '.dial{display:grid;grid-template-columns:78px 1fr;gap:8px;align-items:center;margin-top:7px}.dial .lab{font-size:12px;color:#52525b}',
    '.seg{display:flex;border:1px solid #d4d4d8;border-radius:8px;overflow:hidden}.seg button{flex:1;border:0;border-radius:0;padding:4px 2px;font-size:11.5px;background:#fff;white-space:nowrap}.seg button+button{border-left:1px solid #e4e4e7}.seg button.on{background:#18181b;color:#fff}',
    '.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.chips button{border-radius:999px;padding:3px 10px;font-size:12px}.chips button.on{background:#18181b;color:#fff;border-color:#18181b}',
    '.sw{width:22px;height:22px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #d4d4d8;cursor:pointer;padding:0}.sw.on{box-shadow:0 0 0 2px #18181b}',
    '.site{pointer-events:auto;position:fixed;right:122px;bottom:18px;padding:9px 13px;border-radius:999px;background:#fff;color:#18181b;border:1px solid #e4e4e7;cursor:pointer;box-shadow:0 8px 30px rgba(0,0,0,.14);font-weight:600}',
    // a phone (or a narrow window): the bar wraps — the design's name on its own row, every button reachable
    '@media (max-width:640px){.bar{left:8px;right:8px;bottom:10px;transform:none;max-width:none;flex-wrap:wrap;justify-content:center;gap:6px;padding:8px}.bar .meta{order:-1;flex:1 1 100%;text-align:center}.bar button{padding:5px 8px;font-size:12.5px}}',
    '.spin{width:14px;height:14px;border:2px solid #d4d4d8;border-top-color:#2563eb;border-radius:50%;animation:s .8s linear infinite;display:inline-block;vertical-align:-2px;margin-right:6px}@keyframes s{to{transform:rotate(360deg)}}',
  ].join('') + '</style>';
  (document.body || document.documentElement).appendChild(host);
  var demoCss = document.createElement('style');
  demoCss.textContent = '[data-dh-demo]{text-decoration:underline dashed #f59e0b 1.5px;text-underline-offset:4px}';

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  var pill = el('div', 'pill');
  pill.appendChild(el('span', 'dot'));
  pill.appendChild(el('b', null, 'Try-on'));
  pill.title = 'Deckhand try-on: pick any section or component and try licensed alternatives in your own colours and words';
  root.appendChild(pill);
  var siteBtn = el('div', 'site', 'Site');
  siteBtn.title = 'Tune the whole site: accent colour, warmth, corners, density, headline size, fonts';
  root.appendChild(siteBtn);

  var picking = false, outline = null, tag = null, panel = null, bar = null, session = null, idx = 1, state = null, busy = false;
  var batch = 4;                                   // how many variants a pick (and each More) brings

  /* ------------------------------------------------------------ stamps + slots */
  function fiberOf(n) {
    for (var k in n) if (k.indexOf('__reactFiber$') === 0 || k.indexOf('__reactInternalInstance$') === 0) return n[k];
    return null;
  }
  function firstHost(f) {
    while (f && !(f.stateNode && f.stateNode.nodeType === 1)) f = f.child;
    return f ? f.stateNode : null;
  }
  function crumbsFor(node) {
    var out = [], seen = {};
    function add(stamp, dom, label) {
      if (!stamp || seen[stamp] || /(^|\/)(node_modules|dh-tryon)\//.test(stamp)) return;
      seen[stamp] = 1;
      out.push({ stamp: stamp, el: dom, label: label });
    }
    var f = fiberOf(node);
    if (f) {
      for (var i = 0; f && i < 200; i++, f = f.return) {
        var p = f.memoizedProps;
        if (p && typeof p === 'object' && p['data-dh']) {
          var name = typeof f.type === 'string' ? f.type : (f.type && (f.type.displayName || f.type.name)) || 'component';
          add(p['data-dh'], typeof f.type === 'string' ? f.stateNode : firstHost(f), name);
        }
      }
    }
    for (var n = node; n && n.nodeType === 1; n = n.parentElement) {
      if (n.hasAttribute && n.hasAttribute('data-dh')) add(n.getAttribute('data-dh'), n, n.tagName.toLowerCase());
    }
    out.sort(function (a, b) { return a.el && b.el && a.el !== b.el && a.el.contains(b.el) ? 1 : (a.el && b.el && b.el.contains(a.el) && a.el !== b.el ? -1 : 0); });
    // the innermost few, plus the sections that hold them (a click deep in an accordion still offers the whole FAQ)
    var keep = out.slice(0, 5);
    for (var s = 5; s < out.length && keep.length < 9; s++) {
      var e = out[s].el;
      if (e && (/^(SECTION|HEADER|FOOTER|NAV|MAIN|ARTICLE|ASIDE)$/.test(e.tagName) || BLOCKS.indexOf(guessSlot(e)) >= 0)) keep.push(out[s]);
    }
    return keep;
  }

  var BLOCKS = ['navbar', 'hero', 'logo-cloud', 'features', 'content', 'stats', 'integrations', 'testimonials', 'pricing', 'comparison', 'team', 'faq', 'cta', 'contact', 'footer', 'login', 'signup'];
  function q(n, s) { try { return n.querySelectorAll(s).length; } catch (e) { return 0; } }
  function guessSlot(n) {
    if (!n || n.nodeType !== 1) return null;
    var t = n.tagName.toLowerCase(), cls = String(n.getAttribute('class') || '').toLowerCase();
    if (t === 'body' || t === 'html' || t === 'main') return null;        // the page itself, not one of its sections
    var txt = (n.innerText || '').slice(0, 3000);
    if (t === 'button' || n.getAttribute('role') === 'button' || (t === 'a' && /(btn|button|rounded|bg-|px-)/.test(cls) && q(n, '*') < 6)) return 'button';
    if (t === 'input') return 'input';
    if (t === 'textarea') return 'textarea';
    // shadcn-style components say what they are (<Card> renders data-slot="card")
    var ds = String(n.getAttribute('data-slot') || '');
    if (/^(card|badge|button|input|textarea|avatar|table|tabs|accordion|separator|progress|skeleton|breadcrumb|pagination)$/.test(ds)) return ds;
    if (/badge|chip|pill/.test(cls) && txt.length < 40) return 'badge';
    if (t === 'nav' || (t === 'header' && q(n, 'a') >= 2)) return 'navbar';
    if (t === 'footer') return 'footer';
    if (q(n, 'input[type=password]')) return q(n, 'input') >= 3 ? 'signup' : 'login';
    if (q(n, 'form') && q(n, 'textarea')) return 'contact';
    var prices = (txt.match(/[$€£¥]\s?\d|\d[\d.,]*\s?[$€£¥]/g) || []).length;
    if (prices >= 2 && q(n, 'a,button') >= 2) return 'pricing';
    var qs = 0, heads = n.querySelectorAll('h2,h3,h4,dt,summary,button');
    for (var i = 0; i < heads.length; i++) if (/\?\s*$/.test(heads[i].textContent.trim())) qs++;
    if (qs >= 3) return 'faq';
    if (q(n, 'blockquote') >= 1 || /testimonial|review/.test(cls)) return 'testimonials';
    if (q(n, 'h1')) return 'hero';
    // a table with two or more compared columns (us vs them, plan vs plan)
    if (q(n, 'table') && q(n, 'th') >= 3 && q(n, 'tr') >= 3) return 'comparison';
    // figures: 3+ short leaves that read as a number (120+, 98%, 24h, 7/7, 4.9, €2M) — not a 1, 2, 3 step count
    var figs = 0, leaves = n.querySelectorAll('p,span,div,dt,dd,strong,b,h2,h3,h4');
    for (var f = 0; f < leaves.length && f < 400; f++) {
      if (leaves[f].children.length) continue;
      var ft = (leaves[f].textContent || '').trim();
      if (/^[$€£¥]?\s?\d[\d.,]*\s?(%|\+|[kmb]\+?|x|h|\/\d+)$/i.test(ft) || /^[$€£¥]?\d{1,3}([.,]\d+)+$/.test(ft) || /^\d{3,}$/.test(ft)) figs++;
    }
    // people: 3+ tiles that each hold one portrait and a few short lines (a name, a role)
    function portrait(tile) {
      var ims = tile.querySelectorAll('img,[data-slot=avatar],[class*="avatar"]');
      if (ims.length !== 1) return false;
      var r = ims[0].getBoundingClientRect();
      return r.width >= 48 && r.height >= 0.8 * r.width;          // a face, not a 24px brand mark
    }
    function peopleIn(box) { var k = box.children, x = 0; for (var j = 0; j < k.length; j++) { var tl = (k[j].innerText || '').trim().length; if (tl > 2 && tl < 90 && portrait(k[j])) x++; } return x; }
    // cards: 3+ siblings that each hold a heading and some words — directly, or in the usual container > grid
    function cardsIn(box) { var k = box.children, x = 0; for (var j = 0; j < k.length; j++) if (q(k[j], 'h2,h3,h4') && (k[j].innerText || '').length > 20) x++; return x; }
    var cards = cardsIn(n), boxes = n.querySelectorAll('div,ul,ol');
    for (var b = 0; b < boxes.length && b < 80 && cards < 3; b++) cards = Math.max(cards, cardsIn(boxes[b]));
    if (figs >= 3 && figs >= cards && txt.length < 800) return 'stats';
    var people = peopleIn(n);
    for (var b2 = 0; b2 < boxes.length && b2 < 80 && people < 3; b2++) people = Math.max(people, peopleIn(boxes[b2]));
    if (people >= 3) return 'team';
    if (cards >= 3) return 'features';
    var imgs = q(n, 'img,svg');
    if (imgs >= 4 && txt.replace(/\s/g, '').length < 120) return 'logo-cloud';
    if (q(n, 'h2') >= 1 && q(n, 'a,button') >= 1 && txt.length < 500) return 'cta';
    // an announcement bar: one line and a link across the page
    if (q(n, 'a,button') >= 1 && q(n, 'a,button') <= 2 && !q(n, 'h1,h2,h3,h4,img,input') && txt.length > 12 && txt.length < 200
      && n.getBoundingClientRect().width >= 0.8 * (window.innerWidth || 1)) return 'cta';
    if ((t === 'section' || t === 'article') && q(n, 'h2,h3')) return 'content';
    if (q(n, 'h3,h4') === 1 && txt.length < 500 && /(border|rounded|shadow|card)/.test(cls)) return 'card';
    return null;
  }
  function defaultCrumb(cr, clicked) {
    var ctl = clicked.closest && clicked.closest('button,a,input,textarea,[role=button]');
    if (ctl) {
      // the control itself, else the button that wraps it (<Button asChild><Link>), else something inside it (a label span)
      for (var i = 0; i < cr.length; i++) if (cr[i].el === ctl) return i;
      for (var i2 = 0; i2 < cr.length; i2++) if (cr[i2].el && cr[i2].el.contains(ctl) && guessSlot(cr[i2].el) === 'button') return i2;
      for (var i3 = 0; i3 < cr.length; i3++) if (cr[i3].el && ctl.contains(cr[i3].el)) return i3;
    }
    for (var k = 0; k < cr.length; k++) if (BLOCKS.indexOf(guessSlot(cr[k].el)) >= 0) return k;
    return 0;
  }

  /* ------------------------------------------------------------ palette probe */
  function probe() {
    var cs = getComputedStyle(document.body), counts = {};
    var btns = document.querySelectorAll('button,a');
    for (var i = 0; i < btns.length && i < 200; i++) {
      var b = getComputedStyle(btns[i]).backgroundColor;
      var m = /rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/.exec(b);
      if (!m || (m[4] !== undefined && Number(m[4]) < 0.5)) continue;
      var r = +m[1], g = +m[2], bl = +m[3], mx = Math.max(r, g, bl), mn = Math.min(r, g, bl);
      if (mx - mn < 24) continue;                         // neutral greys/white/black are not an accent
      counts[b] = (counts[b] || 0) + 1;
    }
    var best = null;
    for (var k in counts) if (!best || counts[k] > counts[best]) best = k;
    var bg = cs.backgroundColor;
    return { background: /rgba\(0, 0, 0, 0\)/.test(bg) ? null : bg, foreground: cs.color, primary: best, primaryForeground: best ? '#ffffff' : null };
  }

  /* ------------------------------------------------------------ picking */
  function place(box, r) { box.style.left = r.left + 'px'; box.style.top = r.top + 'px'; box.style.width = r.width + 'px'; box.style.height = r.height + 'px'; }
  function ours(e) { return e.composedPath && e.composedPath().indexOf(host) >= 0; }
  function stampOf(n) { for (; n && n.nodeType === 1; n = n.parentElement) if (n.hasAttribute('data-dh')) return n; return null; }
  function onMove(e) {
    if (!picking || ours(e)) return;
    var t = stampOf(e.target);
    if (!t) return;
    var cr = crumbsFor(e.target), d = cr[defaultCrumb(cr, e.target)] || { el: t, stamp: t.getAttribute('data-dh') };
    var target = d.el || t;
    if (!outline) { outline = el('div', 'outline'); tag = el('div', 'tag'); root.appendChild(outline); root.appendChild(tag); }
    var r = target.getBoundingClientRect();
    place(outline, r);
    tag.textContent = (guessSlot(target) || target.tagName.toLowerCase()) + ' · ' + String(d.stamp).replace(/:\d+$/, '');
    tag.style.left = Math.max(4, r.left) + 'px';
    tag.style.top = Math.max(4, r.top - 26) + 'px';
  }
  function onClick(e) {
    if (!picking || ours(e)) return;
    e.preventDefault(); e.stopPropagation();
    var cr = crumbsFor(e.target);
    if (!cr.length) return;
    stopPicking();
    openPanel(cr, defaultCrumb(cr, e.target));
  }
  function startPicking() { closePanel(); picking = true; pill.classList.add('on'); document.addEventListener('mousemove', onMove, true); document.addEventListener('click', onClick, true); }
  function stopPicking() {
    picking = false; pill.classList.remove('on');
    document.removeEventListener('mousemove', onMove, true); document.removeEventListener('click', onClick, true);
    if (outline) { outline.remove(); tag.remove(); outline = tag = null; }
  }
  pill.addEventListener('click', function () {
    if (session) return;
    if (stale && !picking) { try { sessionStorage.setItem(SS + '-pick', '1'); } catch (e) { /* ignore */ } location.reload(); return; }
    picking ? stopPicking() : startPicking();
  });

  /* ------------------------------------------------------------ panel */
  function closePanel() { if (panel) { panel.remove(); panel = null; } }
  function openPanel(cr, sel) {
    closePanel();
    panel = el('div', 'panel');
    var tabs = el('div', 'tabs'), tSwap = el('button', 'on', 'Swap it'), tTune = el('button', null, 'Tune it');
    tabs.appendChild(tSwap); tabs.appendChild(tTune);
    panel.appendChild(tabs);
    var title = el('p', 'h', 'What do you want to swap?');
    panel.appendChild(title);
    var list = el('div');
    var slotSel = el('select');
    var slots = (state && state.slots) || {};
    var names = ((state && state.allSlots) || Object.keys(slots)).slice().sort();
    function fillSlots(g) {
      slotSel.innerHTML = '';
      var ph = el('option', null, 'choose what this is…'); ph.value = ''; slotSel.appendChild(ph);
      names.forEach(function (s) { var o = el('option', null, s + (slots[s] ? ' (' + slots[s] + ')' : ' — AI draft only')); o.value = s; if (s === g) o.selected = true; slotSel.appendChild(o); });
      syncGo();
    }
    function syncGo() {
      go.disabled = !slotSel.value;
      go.textContent = slotSel.value && !slots[slotSel.value] ? 'Ask AI to draft one' : 'Show variants';
      go.className = slotSel.value && !slots[slotSel.value] ? 'ai' : 'primary';
    }
    var go = el('button', 'primary', 'Show variants');
    cr.forEach(function (c, i) {
      var row = el('div', 'crumb' + (i === sel ? ' sel' : ''));
      var g = guessSlot(c.el);
      row.appendChild(el('div', null, '●'));
      var t = el('div');
      t.appendChild(el('div', null, (g ? g : c.label) + (g ? ' — ' + c.label : '')));
      t.appendChild(el('code', null, String(c.stamp)));
      row.appendChild(t);
      row.addEventListener('click', function () {
        sel = i;
        [].forEach.call(list.children, function (x, k) { x.className = 'crumb' + (k === i ? ' sel' : ''); });
        fillSlots(guessSlot(c.el));
        flash(c.el);
      });
      list.appendChild(row);
    });
    panel.appendChild(list);
    var r1 = el('div', 'row');
    r1.appendChild(slotSel);
    var cnt = el('select');
    [4, 6, 8, 12].forEach(function (n) { var o = el('option', null, n + ' variants'); o.value = n; if (n === batch) o.selected = true; cnt.appendChild(o); });
    cnt.title = 'How many to show at once. More brings the next ones from the pool.';
    r1.appendChild(cnt);
    panel.appendChild(r1);
    var r2 = el('div', 'row');
    var cancel = el('button', null, 'Cancel');
    r2.appendChild(go); r2.appendChild(cancel);
    panel.appendChild(r2);
    var msg = el('div', 'small muted');
    msg.style.marginTop = '10px';
    msg.textContent = 'Variants are real MIT-licensed components, shown in your colours with your text. Nothing ships until you keep one.';
    panel.appendChild(msg);
    var tuneBox = tuneUI(function () {
      var m = /^(.*):(\d+):(\d+)$/.exec(cr[sel].stamp);
      return m ? { file: m[1], line: +m[2], col: +m[3], slot: slotSel.value || guessSlot(cr[sel].el) || 'content', hint: hintOf(cr[sel]) } : null;
    });
    tuneBox.el.style.display = 'none';
    panel.appendChild(tuneBox.el);
    function tab(t) {
      var tune = t === 'tune';
      tSwap.className = tune ? '' : 'on'; tTune.className = tune ? 'on' : '';
      title.textContent = tune ? 'Tune it — your design, adjusted' : 'What do you want to swap?';
      [r1, r2, msg].forEach(function (x) { x.style.display = tune ? 'none' : ''; });
      tuneBox.el.style.display = tune ? '' : 'none';
    }
    tSwap.onclick = function () { tuneBox.reset(); tab('swap'); };
    tTune.onclick = function () { tab('tune'); };
    root.appendChild(panel);
    fillSlots(guessSlot(cr[sel].el));
    slotSel.addEventListener('change', syncGo);
    list.addEventListener('click', function () { tuneBox.reset(); }, true);
    cancel.addEventListener('click', closePanel);
    go.addEventListener('click', function () {
      var m = /^(.*):(\d+):(\d+)$/.exec(cr[sel].stamp);
      if (!m || busy) return;
      var where = { file: m[1], line: +m[2], col: +m[3], slot: slotSel.value, hint: hintOf(cr[sel]) };
      if (!slots[slotSel.value]) { draftForm(panel, where, 'No licensed ' + slotSel.value + ' designs exist for this site yet.'); return; }
      busy = true; go.disabled = true; batch = +cnt.value;
      msg.className = 'small';
      msg.innerHTML = '<span class="spin"></span>Fetching, theming and filling variants with your content…';
      api('open', { file: where.file, line: where.line, col: where.col, slot: where.slot, count: +cnt.value, probe: probe(),
        page: location.pathname + location.search, hint: hintOf(cr[sel]) }).then(function (r) {
        busy = false;
        if (!r.ok) {
          go.disabled = false; msg.className = 'err'; msg.textContent = (r.code || 'ERROR') + ': ' + r.message + skippedText(r.skipped) + keptText(r);
          if (r.reload) reloadButton(msg);
          if (r.draft) { r.draft.hint = hintOf(cr[sel]); draftForm(panel, r.draft, 'None of the licensed designs could hold your content.'); }
          return;
        }
        closePanel();
        startSession(r, 1);
      }).catch(function (e) { busy = false; go.disabled = false; msg.className = 'err'; msg.textContent = String(e); });
    });
  }
  /* ------------------------------------------------------------ Tune (knobs on one element, no AI) */
  var DIALS = [
    ['density', 'Spacing', [-2, -1, 0, 1, 2], ['tight', 'snug', 'as is', 'airy', 'open']],
    ['size', 'Headlines', [-2, -1, 0, 1, 2], ['xs', 'small', 'as is', 'large', 'xl']],
    ['weight', 'Weight', [-1, 0, 1, 2], ['lighter', 'as is', 'bolder', 'heavy']],
    ['corners', 'Corners', ['sharp', 'soft', 'as is', 'round', 'pill'], ['sharp', 'soft', 'as is', 'round', 'pill']],
    ['depth', 'Depth', ['flat', 'subtle', 'as is', 'raised'], ['flat', 'subtle', 'as is', 'raised']],
    ['contrast', 'Contrast', ['soft', 'as is', 'crisp'], ['soft', 'as is', 'crisp']],
    ['width', 'Width', [-1, 0, 1, 2], ['narrower', 'as is', 'wider', 'widest']],
  ];
  var PRESETS = ['quieter', 'bolder', 'airy', 'compact', 'clarity', 'softer', 'sharper'];
  function tuneUI(where) {
    var box = el('div'), sess = null, dials = {}, preset = null, pending = null, running = false, lastKnob = null;
    // why a knob found nothing, and where the owner can get it instead
    var WHY = {
      corners: 'No corner classes on this element itself — buttons and cards usually take theirs from your ui components. Site → Corners rounds the whole site.',
      depth: 'No shadow classes on this element itself. Site changes the whole look; or pick the card inside.',
      width: 'No width limit (max-w-…) on this element to widen or narrow — pick its inner container.',
      contrast: 'No muted or secondary text colours here to soften or sharpen.',
      size: 'No headline sizes (text-…) in this element.', weight: 'No font weights in this element.', density: 'No spacing classes (p-, gap-, space-, m-) in this element.',
    };
    var chips = el('div', 'chips'), status = el('div', 'small muted');
    status.style.marginTop = '8px';
    status.textContent = 'Each change is written to your code and shown live; Keep to finish, Reset to undo.';
    PRESETS.forEach(function (p) {
      var b = el('button', null, p);
      b.onclick = function () { preset = preset === p ? null : p; dials = {}; lastKnob = null; render(); push(); };
      chips.appendChild(b);
    });
    box.appendChild(el('div', 'small muted', 'One click:'));
    box.appendChild(chips);
    var rows = el('div');
    box.appendChild(rows);
    function render() {
      [].forEach.call(chips.children, function (b) { b.className = b.textContent === preset ? 'on' : ''; });
      rows.innerHTML = '';
      DIALS.forEach(function (d) {
        var row = el('div', 'dial'), seg = el('div', 'seg');
        row.appendChild(el('div', 'lab', d[1]));
        var cur = dials[d[0]] !== undefined ? dials[d[0]] : (d[2].indexOf(0) >= 0 ? 0 : 'as is');
        d[2].forEach(function (v, i) {
          var b = el('button', v === cur ? 'on' : null, d[3][i]);
          b.onclick = function () { dials[d[0]] = v; lastKnob = d[0]; render(); push(); };
          seg.appendChild(b);
        });
        row.appendChild(seg);
        rows.appendChild(row);
      });
    }
    function push() {
      pending = { dials: Object.assign({}, dials), preset: preset };
      if (running) return;
      running = true;
      (function next() {
        var job = pending; pending = null;
        var go = sess ? Promise.resolve({ ok: true, id: sess }) : api('tune-open', where());
        go.then(function (o) {
          if (!o.ok) throw o;
          sess = o.id;
          status.innerHTML = '<span class="spin"></span>Writing it to your code…';
          return api('tune-set', { id: sess, dials: job.dials, preset: job.preset });
        }).then(function (r) {
          if (!r.ok) throw r;
          status.className = 'small'; status.textContent = r.changed ? 'Live on the page (' + r.changed + ' class changes). Keep it, or Reset.' : 'Nothing to change there for this knob. ' + ((lastKnob && WHY[lastKnob]) || '');
        }).catch(function (e) { status.className = 'err'; status.textContent = (e.code || 'ERROR') + ': ' + (e.message || e); })
          .then(function () { if (pending) next(); else running = false; });
      })();
    }
    render();
    var r = el('div', 'row'), keep = el('button', 'primary', 'Keep'), reset = el('button', null, 'Reset'), ai = el('button', 'ai', 'Describe it to the AI'), close = el('button', null, 'Close');
    r.appendChild(keep); r.appendChild(reset); r.appendChild(ai); r.appendChild(close);
    close.onclick = function () { doReset().then(closePanel); };              // unkept changes never linger
    box.appendChild(r);
    box.appendChild(status);
    keep.onclick = function () {
      if (!sess) return;
      api('tune-keep', { id: sess }).then(function (x) { sess = null; dials = {}; preset = null; render(); status.className = 'ok'; status.textContent = x.ok ? 'Kept in ' + x.file + '.' : x.message; });
    };
    function doReset() {
      if (!sess) return Promise.resolve();
      var id = sess; sess = null; dials = {}; preset = null; render();
      return api('tune-reset', { id: id }).then(function (x) {
        status.className = x.ok ? 'small muted' : 'err';
        status.textContent = !x.ok ? (x.code || 'ERROR') + ': ' + x.message
          : x.mode === 'byte-exact' ? 'Back to the original (byte-exact).'
          : 'The knobs are undone; your own edits to ' + x.restored + ' are kept.' + (x.note ? ' ' + x.note : '');
      });
    }
    reset.onclick = doReset;
    ai.onclick = function () { doReset().then(function () { var w = where(); if (w) draftForm(box, w, 'Knobs not enough?'); }); };
    return { el: box, reset: doReset };
  }

  /* ------------------------------------------------------------ Site (the whole look, previewed exactly) */
  var themeSet = [];
  function clearPreview() {
    themeSet.forEach(function (k) { document.documentElement.style.removeProperty(k); });
    themeSet = [];
    var f = document.getElementById('dh-font-preview'); if (f) f.remove();
    var l = document.getElementById('dh-font-link'); if (l) l.remove();
  }
  function sitePanel() {
    closePanel();
    panel = el('div', 'panel');
    panel.appendChild(el('p', 'h', 'The whole site'));
    var body = el('div', 'small muted', 'Loading…');
    panel.appendChild(body);
    root.appendChild(panel);
    api('theme-state').then(function (st) {
      body.innerHTML = '';
      if (!st.ok) { body.className = 'err'; body.textContent = st.message; return; }
      var v = Object.assign({}, st.current), status = el('div', 'small muted');
      status.style.marginTop = '8px';
      status.textContent = 'Preview only — nothing is written until Apply.';
      function seg(label, key, opts) {
        var row = el('div', 'dial'), sg = el('div', 'seg');
        row.appendChild(el('div', 'lab', label));
        opts.forEach(function (o) {
          var b = el('button', (v[key] || 'as is') === o ? 'on' : null, o);
          b.onclick = function () { v[key] = o; [].forEach.call(sg.children, function (x) { x.className = x === b ? 'on' : ''; }); preview(); };
          sg.appendChild(b);
        });
        row.appendChild(sg);
        body.appendChild(row);
      }
      var arow = el('div', 'dial'), sws = el('div', 'chips');
      arow.appendChild(el('div', 'lab', 'Accent'));
      Object.keys(st.accents).forEach(function (k) {
        var b = el('button', 'sw' + (v.accent === k ? ' on' : ''));
        b.style.background = st.accents[k]; b.title = k;
        b.onclick = function () { v.accent = k; [].forEach.call(sws.children, function (x) { if (x.classList.contains('sw')) x.className = 'sw' + (x === b ? ' on' : ''); }); preview(); };
        sws.appendChild(b);
      });
      var pick = el('input'); pick.type = 'color'; pick.title = 'your own colour'; pick.style.width = '30px'; pick.style.height = '24px';
      pick.oninput = function () { v.accent = pick.value; preview(); };
      sws.appendChild(pick);
      arow.appendChild(sws);
      body.appendChild(arow);
      seg('Neutrals', 'neutrals', st.knobs.neutrals);
      seg('Corners', 'corners', st.knobs.corners);
      if (st.spacingVar) seg('Density', 'density', st.knobs.density);
      seg('Headlines', 'headlines', st.knobs.headlines);
      if (st.fonts) {
        ['body', 'heading'].forEach(function (role) {
          var row = el('div', 'dial'), sel = el('select');
          row.appendChild(el('div', 'lab', role === 'body' ? 'Body font' : 'Heading font'));
          var o0 = el('option', null, 'as is'); o0.value = ''; sel.appendChild(o0);
          st.fonts.list.forEach(function (f) { var o = el('option', null, f.google + ' (' + f.kind + ')'); o.value = f.id; if (v[role] === f.id) o.selected = true; sel.appendChild(o); });
          sel.onchange = function () { v[role] = sel.value || undefined; preview(); };
          row.appendChild(sel);
          body.appendChild(row);
        });
      }
      function preview() {
        api('theme-vars', v).then(function (r) {
          if (!r.ok) return;
          clearPreview();
          var dark = document.documentElement.classList.contains('dark');
          var vars = Object.assign({}, r.light, dark ? r.dark : {});
          Object.keys(vars).forEach(function (k) { document.documentElement.style.setProperty('--' + k, vars[k]); themeSet.push('--' + k); });
          var fam = function (id) { var f = st.fonts && st.fonts.list.filter(function (x) { return x.id === id; })[0]; return f ? f.google : null; };
          var b = fam(v.body), h = fam(v.heading);
          if (b || h) {
            var link = document.createElement('link'); link.id = 'dh-font-link'; link.rel = 'stylesheet';
            link.href = 'https://fonts.googleapis.com/css2?' + [b, h].filter(Boolean).map(function (x) { return 'family=' + x.replace(/ /g, '+'); }).join('&') + '&display=swap';
            document.head.appendChild(link);
            var st2 = document.createElement('style'); st2.id = 'dh-font-preview';
            // the same reach as apply: body inherits it, explicit font utilities keep theirs
            var kind = function (id) { var f = st.fonts && st.fonts.list.filter(function (x) { return x.id === id; })[0]; return f && f.kind; };
            var stack = function (id) { var k = kind(id); return k === 'serif' ? 'ui-serif,Georgia,serif' : k === 'mono' ? 'ui-monospace,monospace' : 'ui-sans-serif,system-ui,sans-serif'; };
            st2.textContent = (b ? 'html body{font-family:"' + b + '",' + stack(v.body) + '}' : '') + (h ? 'html body :is(h1,h2,h3){font-family:"' + h + '",' + stack(v.heading) + '}' : '');
            document.head.appendChild(st2);
          }
          status.className = 'small'; status.textContent = 'Previewing (exact values). Apply writes them to your stylesheet' + (b || h ? ' and layout' : '') + '.';
        });
      }
      body.appendChild(status);
      var r = el('div', 'row'), apply = el('button', 'primary', 'Apply to the site'), undo = el('button', null, 'Undo last apply'), close = el('button', null, 'Close');
      undo.disabled = !st.undo;
      r.appendChild(apply); r.appendChild(undo); r.appendChild(close);
      body.appendChild(r);
      apply.onclick = function () {
        apply.disabled = true;
        api('theme-apply', v).then(function (x) {
          apply.disabled = false;
          if (!x.ok) { status.className = 'err'; status.textContent = x.code + ': ' + x.message; return; }
          status.className = 'ok'; status.textContent = 'Applied to ' + x.files.join(' + ') + '.';
          undo.disabled = false;
          setTimeout(clearPreview, 2500);                              // the dev server now serves the same values
        });
      };
      undo.onclick = function () {
        api('theme-undo').then(function (x) {
          clearPreview(); status.className = x.ok ? 'ok' : 'err';
          status.textContent = x.ok ? 'Restored ' + x.restored.join(' + ') + ' (byte-exact)' + (x.more ? ' — ' + x.more + ' earlier apply(s) can be undone too.' : ' — back to before the first apply.') : x.message;
          undo.disabled = !(x.ok && x.more);
        });
      };
      close.onclick = function () { clearPreview(); closePanel(); };
    });
  }
  siteBtn.addEventListener('click', function () { if (session) return; stopPicking(); sitePanel(); });

  /* ------------------------------------------------------------ AI draft (the fallback, labelled) */
  function draftForm(container, where, why) {
    var old = container.querySelector('.ai-box'); if (old) old.remove();
    var box = el('div', 'ai-box');
    box.appendChild(el('div', null, why + ' Your AI agent can write one for this element.'));
    var how = el('div', 'small');
    how.style.marginTop = '6px';
    how.textContent = 'It will be labelled AI-generated. Deckhand checks it before you see it: your colours, all your words and links, no invented facts, nothing to install.';
    box.appendChild(how);
    var note = el('textarea');
    note.placeholder = 'What should it look like? (optional) e.g. "image on the left, big serif title"';
    box.appendChild(note);
    var row = el('div', 'row');
    var ask = el('button', 'ai', 'Ask AI to draft one');
    row.appendChild(ask);
    box.appendChild(row);
    container.appendChild(box);
    ask.onclick = function () {
      ask.disabled = true;
      api('draft', { file: where.file, line: where.line, col: where.col, slot: where.slot, session: where.session, hint: where.hint || null, note: note.value.trim() || null }).then(function (r) {
        if (!r.ok) { ask.disabled = false; var er = el('div', 'err', (r.code || 'ERROR') + ': ' + r.message); box.appendChild(er); if (r.reload) reloadButton(er); return; }
        waitDraft(r);
      });
    };
  }
  function waitDraft(d) {
    closePanel();
    panel = el('div', 'panel');
    panel.appendChild(el('p', 'h', 'AI draft requested'));
    var st = el('div', 'small');
    st.innerHTML = '<span class="spin"></span>Waiting for your AI agent to write it…';
    panel.appendChild(st);
    var tip = el('div', 'small muted');
    tip.style.marginTop = '8px';
    tip.textContent = 'If your agent is not watching try-on, tell it:';
    panel.appendChild(tip);
    panel.appendChild(el('code', 'say', 'Write the try-on AI draft ' + d.id));
    var row = el('div', 'row');
    var close = el('button', null, 'Hide');
    close.onclick = closePanel;
    row.appendChild(close);
    panel.appendChild(row);
    root.appendChild(panel);
    try { sessionStorage.setItem(SS + '-draft', d.id); } catch (e) { /* private mode */ }
    (function poll() {
      api('draft-status', { id: d.id }).then(function (r) {
        if (!r.ok) { st.className = 'err'; st.textContent = r.code + ': ' + r.message; return; }
        var x = r.draft;
        if (x.state === 'done' && r.session) {
          try { sessionStorage.removeItem(SS + '-draft'); } catch (e) { /* ignore */ }
          closePanel();
          session = null;
          if (bar) { bar.remove(); bar = null; }
          var ai = 1;
          r.session.variants.forEach(function (v) { if (v.generated) ai = v.idx; });
          startSession(r.session, ai);
          return;
        }
        if (x.state === 'done' && !r.session) {
          try { sessionStorage.removeItem(SS + '-draft'); } catch (e) { /* ignore */ }
          st.className = 'small'; st.textContent = 'This AI draft was already shown and closed.';
          return;
        }
        if (x.state === 'rejected') {
          st.className = 'small';
          st.innerHTML = '<span class="spin"></span>';
          st.appendChild(document.createTextNode('The draft failed ' + x.problems.length + ' check(s); your agent is fixing it: ' + x.problems.slice(0, 3).map(function (p) { return p.detail; }).join(' · ')));
        }
        setTimeout(poll, 2000);
      }).catch(function () { setTimeout(poll, 4000); });
    })();
  }

  // what the element IS (tag + the start of its text): the engine finds it again when the page is older than the file
  function hintOf(c) {
    if (!c) return null;
    var text = '';
    try { text = String((c.el && c.el.innerText) || '').replace(/\s+/g, ' ').trim().slice(0, 80); } catch (e) { /* detached */ }
    return { tag: String(c.label || ''), text: text };
  }
  function reloadButton(where) {
    var b = el('button', 'primary', 'Reload the page and pick again');
    b.style.marginTop = '8px';
    b.onclick = function () { try { sessionStorage.setItem(SS + '-pick', '1'); } catch (e) { /* ignore */ } location.reload(); };
    where.appendChild(document.createElement('br'));
    where.appendChild(b);
  }
  // after Keep/Discard the file moved under the page: the next pick starts from a fresh page (fresh positions)
  var stale = false;
  function keptText(r) { return r && r.installedKept && r.installedKept.length ? '\n\nInstalled for this try and kept in package.json: ' + r.installedKept.join(', ') : ''; }
  var WHY = { POOR_FIT: 'no room for your content', FETCH_FAILED: 'download failed', NEEDS_DEPS: 'needs npm packages', UNRESOLVED_IMPORT: 'broken upstream',
    BROKEN_IMPORT: 'would break this page', NO_EXPORT: 'broken upstream', PARAMETERIZE_FAILED: 'could not be adapted', FETCH: 'download failed' };
  function skippedText(sk) {
    if (!sk || !sk.length) return '';
    var by = {}, order = [];
    sk.forEach(function (s) { var w = WHY[s.why] || s.why; if (!by[w]) { by[w] = []; order.push(w); } by[w].push(String(s.id).replace(/@[\w-]+$/, '')); });
    return '\n\nskipped: ' + order.map(function (w) { return by[w].length + ' ' + w + ' (' + by[w].slice(0, 3).join(', ') + (by[w].length > 3 ? ', …' : '') + ')'; }).join(' · ');
  }
  function flash(n) { if (!n) return; var o = el('div', 'outline'); root.appendChild(o); place(o, n.getBoundingClientRect()); setTimeout(function () { o.remove(); }, 700); }

  /* ------------------------------------------------------------ session / variant bar */
  function wrappers() { return document.querySelectorAll('[data-dh-session="' + session.id + '"]'); }
  function apply(i) {
    idx = i;
    var ws = wrappers(), first = null;
    for (var w = 0; w < ws.length; w++) {
      var vs = ws[w].querySelectorAll(':scope > [data-dh-variant]');
      for (var k = 0; k < vs.length; k++) {
        var on = Number(vs[k].getAttribute('data-dh-variant')) === i;
        vs[k].style.display = on ? 'contents' : 'none';
        if (on && !first) first = vs[k];
      }
    }
    try { sessionStorage.setItem(SS, JSON.stringify({ id: session.id, idx: i })); } catch (e) { /* private mode */ }
    renderBar();
    if (first) {
      var t = first.firstElementChild;
      if (t) { var r = t.getBoundingClientRect(); if (r.top < 0 || r.top > innerHeight * 0.6) t.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
    }
  }
  function startSession(s, i) {
    session = s; idx = i;
    document.head.appendChild(demoCss);
    renderBar('<span class="spin"></span>Waiting for your dev server to render the variants…');
    var t0 = Date.now();
    (function wait() {
      if (!session) return;
      if (wrappers().length) { apply(idx); return; }
      if (Date.now() - t0 > 45000) { renderBar('The variants were written, but the page did not update. Check the dev-server terminal for a compile error, or Discard.'); return; }
      setTimeout(wait, 250);
    })();
  }
  function renderBar(note) {
    if (!bar) { bar = el('div', 'bar'); root.appendChild(bar); }
    bar.innerHTML = '';
    var vs = session.variants, v = vs[idx] || vs[0];
    var prev = el('button', null, '◀'), next = el('button', null, '▶');
    var count = el('span', 'count', idx + ' / ' + (vs.length - 1));
    if (idx === 0) count.textContent = 'original';
    var meta = el('div', 'meta');
    var name = el('div', 'name', v.t);
    if (v.generated) name.appendChild(el('span', 'fit ai', 'AI-generated'));
    if (v.fit && v.fit.of) {
      var f = el('span', 'fit ' + (v.fit.carried >= v.fit.of ? 'g' : 'y'), 'your content ' + v.fit.carried + '/' + v.fit.of);
      name.appendChild(f);
    }
    meta.appendChild(name);
    var sub = note ? '' : (v.r === 'yours' ? 'your current version'
      : v.generated ? 'written by your AI agent, not a licensed human design' + (v.fit && v.fit.demo && v.fit.demo.length ? ' · its own words: ' + v.fit.demo.slice(0, 3).map(function (t) { return t.replace(/^AI-written: /, '“') + '”'; }).join(' ') : '')
      : (v.r + ' · ' + (v.lic || 'MIT') + (v.fit && v.fit.demo && v.fit.demo.length ? ' · demo copy (dashed): ' + v.fit.demo.slice(0, 2).join(' · ') : '')));
    if (!note && session.dropped && session.dropped.length) sub += ' · ' + session.dropped.length + ' variant(s) removed: they broke your page build';
    var subEl = el('div', 'sub'); if (note) subEl.innerHTML = note; else subEl.textContent = sub;
    meta.appendChild(subEl);
    var keep = el('button', 'keep', 'Keep'), orig = el('button', null, 'Original'), disc = el('button', null, 'Discard');
    // the pool: how many designs this element has not been shown yet (More brings the next batch after these)
    var pool = session.pool, full = vs.length - 1 >= (session.max || 30);
    var more = el('button', null, pool ? (pool.left ? 'More · ' + pool.left + ' left' : 'No more') : 'More');
    more.title = full ? 'This try holds the most variants it can: keep one, or discard and pick again'
      : pool ? pool.left + ' of ' + pool.total + ' ' + session.slot + ' designs not shown yet — the next ' + Math.min(batch, pool.left) + ' come after these' : 'The next designs from the pool';
    var aiBtn = el('button', 'ai', 'AI draft');
    aiBtn.title = 'Ask your AI agent to write one more version for this element (labelled AI-generated)';
    [prev, count, next, meta, orig, keep, more, aiBtn, disc].forEach(function (x) { bar.appendChild(x); });
    aiBtn.onclick = function () {
      closePanel();
      panel = el('div', 'panel');
      panel.appendChild(el('p', 'h', 'AI draft for this ' + session.slot));
      root.appendChild(panel);
      draftForm(panel, { session: session.id, slot: session.slot }, 'The licensed designs are shown.');
    };
    prev.onclick = function () { apply((idx - 1 + vs.length) % vs.length); };
    next.onclick = function () { apply((idx + 1) % vs.length); };
    orig.onclick = function () { apply(0); };
    keep.onclick = doKeep;
    disc.onclick = doDiscard;
    more.onclick = doMore;
    if (busy || note) [prev, next, orig, keep, more, aiBtn].forEach(function (b) { b.disabled = true; });
    if ((pool && !pool.left) || full) more.disabled = true;
  }
  function endSession() {
    session = null;
    try { sessionStorage.removeItem(SS); } catch (e) { /* ignore */ }
    if (demoCss.parentNode) demoCss.remove();
    if (bar) { bar.remove(); bar = null; }
  }
  function doKeep() {
    if (busy) return;
    busy = true;
    var s = session, i = idx;
    renderBar('<span class="spin"></span>Keeping it — baking your text into the component…');
    api('keep', { id: s.id, idx: i }).then(function (r) {
      busy = false;
      if (!r.ok) { renderBar(r.code + ': ' + r.message); return; }
      endSession();
      stale = true;
      toast('Kept “' + (r.kept || 'original') + '”' + (r.component ? ' → ' + r.component : ''), r.component ? s.id : null);
    });
  }
  function doDiscard() {
    if (busy) return;
    busy = true;
    api('discard', { id: session.id }).then(function (r) {
      busy = false;
      endSession();
      stale = true;
      toast(r.ok ? 'Discarded — your file is restored (' + r.mode + '). The next pick reloads the page first.'
        + (r.installedKept ? ' Installed for this try and kept in package.json: ' + r.installedKept.join(', ') + '.' : '') : r.code + ': ' + r.message);
    });
  }
  function doMore() {
    if (busy || !session) return;
    busy = true;
    var sid = session.id, was = session;
    renderBar('<span class="spin"></span>Fetching the next ' + batch + ' from the pool — the ones you saw stay…');
    api('more', { id: sid, batch: batch, probe: probe(), page: location.pathname + location.search }).then(function (r) {
      busy = false;
      // the pool is spent or the try is full: nothing was touched, keep comparing
      if (!r.ok && (r.code === 'POOL_EMPTY' || r.code === 'TOO_MANY_VARIANTS')) { session = was; if (r.pool) session.pool = r.pool; renderBar(); moreNote(r.message); return; }
      if (!r.ok) { session = null; endSession(); stale = true; toast(r.code + ': ' + r.message + keptText(r)); return; }
      session = null;
      startSession(r, r.startAt || 1);
      if (!r.added) moreNote('No new design could hold your content this time; the ones you saw are back.');
    }).catch(function (e) { busy = false; session = was; renderBar(); moreNote(String(e)); });
  }
  function moreNote(text) {
    var t = el('div', 'panel');
    t.appendChild(el('div', 'small', text));
    var ok = el('button', null, 'OK'); ok.style.marginTop = '8px'; ok.onclick = function () { t.remove(); if (panel === t) panel = null; };
    t.appendChild(ok);
    closePanel(); root.appendChild(t); panel = t;
  }
  function toast(text, keptId) {
    var t = el('div', 'panel');
    t.appendChild(el('div', 'ok', text));
    var row = el('div', 'row');
    if (keptId) {
      var save = el('button', 'blue', 'Save to my library');
      save.onclick = function () {
        save.disabled = true;
        api('save', { id: keptId }).then(function (r) { save.textContent = r.ok ? 'Saved — ranks first next time' : (r.code + ': ' + r.message); });
      };
      row.appendChild(save);
    }
    var done = el('button', null, 'Done');
    done.onclick = function () { t.remove(); };
    row.appendChild(done);
    t.appendChild(row);
    closePanel();
    root.appendChild(t);
    panel = t;
  }

  document.addEventListener('keydown', function (e) {
    if (!session || busy || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || '')) return;
    var n = session.variants.length;
    if (e.key === 'ArrowRight') { apply((idx + 1) % n); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { apply((idx - 1 + n) % n); e.preventDefault(); }
    else if (e.key === 'Enter') { doKeep(); e.preventDefault(); }
    else if (e.key === 'Escape') { doDiscard(); e.preventDefault(); }
  });

  /* ------------------------------------------------------------ boot: resume an open session */
  api('state').then(function (r) {
    state = r;
    var saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(SS) || 'null'); } catch (e) { /* ignore */ }
    var open = (r.open || [])[0];
    if (open) startSession(open, saved && saved.id === open.id ? saved.idx : open.shown || 1);
    var pick = null;
    try { pick = sessionStorage.getItem(SS + '-pick'); sessionStorage.removeItem(SS + '-pick'); } catch (e) { /* ignore */ }
    if (pick && !open) startPicking();
    var waiting = null;
    try { waiting = sessionStorage.getItem(SS + '-draft'); } catch (e) { /* ignore */ }
    (r.drafts || []).forEach(function (d) { if (d.id === waiting) waitDraft(d); });
  });
  window.__dhTryon = { api: api, crumbsFor: crumbsFor, guessSlot: guessSlot, probe: probe };
})();
