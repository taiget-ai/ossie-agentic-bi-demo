const $ = id => document.getElementById(id);
let lang = localStorage.getItem('ossie-language') === 'en' ? 'en' : 'zh';
let current = null, planOnly = false, catalog = null, history = [], selected = null;
let periodResult = null, modelResult = null, metricResult = null, activeTable = 'players', busy = false;
const defaultQuestions = {
  zh: '按国家统计总投注额、总充值额、投注人数和人均投注额',
  en: 'Show total stake, total deposit, unique bettors and stake per bettor by country'
};
const t = (en, zh) => lang === 'zh' ? zh : en;

const names = {
  day: '日', week: '周', month: '月',
  total_stake: '总投注额', total_deposit: '总充值额',
  stake_per_bettor: '人均投注额', unique_bettors: '去重投注人数',
  bet_count: '投注次数', deposit_count: '充值次数', ngr: '净收入 (NGR)',
  country: '国家', game_category: '游戏类别', time_period: '时间周期',
  previous: '上期 / 原口径', current: '本期', candidate: '候选口径',
  delta: '变化量 (Δ)', change_pct: '变化率 %', contribution_pct: '净变化贡献 %',
  group: '分组', explain_numerator: '分子', explain_denominator: '分母'
};
const countryNames = {
  SG: 'SG · 新加坡', FI: 'FI · 芬兰', DE: 'DE · 德国', US: 'US · 美国',
  GB: 'GB · 英国', CA: 'CA · 加拿大', AU: 'AU · 澳大利亚', JP: 'JP · 日本',
  IN: 'IN · 印度', BR: 'BR · 巴西', FR: 'FR · 法国', ES: 'ES · 西班牙'
};
const label = key => lang === 'zh' ? (names[key] || key) : key;
const node = (tag, text, cls) => { const e = document.createElement(tag); e.textContent = text; if (cls) e.className = cls; return e; };
const fmt = value => value == null ? '—' : typeof value === 'number'
  ? new Intl.NumberFormat(lang === 'zh' ? 'zh-CN' : 'en-US', { maximumFractionDigits: 2 }).format(value)
  : (lang === 'zh' && countryNames[value] ? countryNames[value] : String(value));

function button(text, action, cls = 'secondary') {
  const b = node('button', text, cls);
  b.type = 'button';
  b.onclick = action;
  return b;
}

function activateTab(tabName) {
  document.querySelectorAll('.nav-tab').forEach(btn => {
    const active = btn.dataset.tab === tabName;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', String(active));
    btn.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.hidden = pane.id !== `tab-${tabName}`;
  });
}

document.querySelectorAll('.nav-tab').forEach(btn => {
  btn.id = `nav-${btn.dataset.tab}`;
  btn.setAttribute('role', 'tab');
  btn.setAttribute('aria-controls', `tab-${btn.dataset.tab}`);
  const pane = $(`tab-${btn.dataset.tab}`);
  pane.setAttribute('role', 'tabpanel');
  pane.setAttribute('aria-labelledby', btn.id);
  btn.onclick = () => activateTab(btn.dataset.tab);
  btn.onkeydown = event => {
    const tabs = [...document.querySelectorAll('.nav-tab')];
    const index = tabs.indexOf(btn);
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
    if (next !== null) {
      event.preventDefault();
      activateTab(tabs[next].dataset.tab);
      tabs[next].focus();
    }
  };
});

if ($('peek-sql-btn')) {
  $('peek-sql-btn').onclick = () => activateTab('inspector');
}

function jsonDetails(target, value) {
  const d = node('details', '');
  d.append(node('summary', t('Technical trace & SQL evidence', '查看底层 SQL 证据与指纹详情')), node('pre', JSON.stringify(value, null, 2)));
  target.append(d);
}

function table(target, rows, interactive = false) {
  target.replaceChildren();
  if (!rows.length) {
    target.textContent = t('No records returned.', '没有匹配的记录。');
    return;
  }
  const wrap = node('div', '', 'scroll-table'), tbl = node('table', ''), head = node('tr', '');
  const keys = Object.keys(rows[0]);
  keys.forEach(k => {
    const th = node('th', label(k), rows.some(row => typeof row[k] === 'number') ? 'numeric' : '');
    th.scope = 'col';
    head.append(th);
  });
  if (interactive) head.append(node('th', t('Explore', '探索')));
  tbl.append(head);

  const colMax = {};
  if (interactive && current?.semantic_query?.metrics) {
    for (const m of current.semantic_query.metrics) {
      const vals = rows.map(r => typeof r[m] === 'number' ? Math.abs(r[m]) : 0);
      colMax[m] = Math.max(...vals, 1);
    }
  }

  rows.forEach(row => {
    const tr = node('tr', '');
    Object.entries(row).forEach(([k, v]) => {
      const td = node('td', '', typeof v === 'number' ? 'numeric' : '');
      if (interactive && current.semantic_query.metrics.includes(k)) {
        const cellWrap = node('div', '', 'metric-cell-wrap');
        const btn = button(fmt(v), () => explain(k, row), 'cell-button');
        btn.title = t('Click to inspect formula & numerator/denominator', '点击查看该指标计算公式与分子/分母拆解');
        cellWrap.append(btn);
        if (typeof v === 'number' && colMax[k] > 0) {
          const track = node('div', '', 'data-bar-track');
          const fill = node('div', '', 'data-bar-fill');
          fill.style.width = `${Math.min(100, Math.round((Math.abs(v) / colMax[k]) * 100))}%`;
          track.append(fill);
          cellWrap.append(track);
        }
        td.append(cellWrap);
      } else {
        td.textContent = fmt(v);
      }
      tr.append(td);
    });
    if (interactive) {
      const td = node('td', '');
      const dBtn = button(t('Drill down ↘', '下钻 ↘'), () => chooseDrill(row), 'drill-btn');
      td.append(dBtn);
      tr.append(td);
    }
    tbl.append(tr);
  });
  wrap.append(tbl);
  target.append(wrap);
}

async function post(path, body, binary = false) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) {
    const e = await r.json();
    throw new Error((e.error?.stage ? `[${e.error.stage}] ` : '') + (e.error?.message || e.detail));
  }
  return binary ? r.blob() : r.json();
}

async function action(fn, target = $('status')) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button:not(.nav-tab)').forEach(b => b.disabled = true);
  target.textContent = t('Working…', '正在执行…');
  try {
    await fn();
  } catch (e) {
    target.textContent = t('Unable to complete: ', '无法完成：') + e.message;
  } finally {
    busy = false;
    document.querySelectorAll('button:not(.nav-tab)').forEach(b => b.disabled = false);
    $('export').disabled = !current || planOnly;
    $('compare-model').disabled = !current;
  }
}

function switchMode() {
  $('structured-box').hidden = $('mode').value !== 'structured';
  $('question-box').hidden = $('mode').value === 'structured';
  $('provider').hidden = $('mode').value !== 'llm';
  $('plan-only').hidden = $('mode').value !== 'structured';
}

function query() {
  return current?.semantic_query || JSON.parse($('structured').value);
}

function clear() {
  current = null; selected = null; metricResult = null;
  $('metric-panel').hidden = true;
  $('drill-controls').hidden = true;
  if ($('active-query-bar')) $('active-query-bar').hidden = true;
  if ($('breadcrumbs-wrap')) $('breadcrumbs-wrap').hidden = true;
  $('branches').replaceChildren();
  $('results').replaceChildren();
  $('merge-summary').hidden = true;
  for (const id of ['semantic', 'logical', 'sql', 'inspection-summary', 'inspection-state', 'breadcrumbs']) {
    if ($(id)) $(id).textContent = '';
  }
  $('export').disabled = true;
  $('compare-model').disabled = true;
  $('sandbox-empty').hidden = false;
}

async function run(only = false) {
  await action(async () => {
    clear();
    history = [];
    let body, path;
    if ($('mode').value === 'structured') {
      body = JSON.parse($('structured').value);
      path = only ? '/api/plan' : '/api/query';
    } else {
      body = { question: $('question').value, mode: $('mode').value };
      path = '/api/ask';
      if (body.mode === 'llm') {
        body.llm = {
          base_url: $('base-url').value || null,
          model: $('model').value || null,
          api_key: $('api-key').value || null,
          json_mode: $('json-mode').checked
        };
      }
    }
    current = await post(path, body);
    planOnly = only;
    history = [current];
    renderCurrent();
    $('status').textContent = t('Query completed', '查询完成');
  });
}

function renderCatalogStrip() {
  const strip = $('catalog-strip');
  if (!strip || !catalog) return;
  strip.replaceChildren();
  const mRow = node('div', '', 'catalog-row');
  mRow.append(node('span', t('Metrics:', '指标：'), 'catalog-title'));
  for (const m of catalog.metrics) {
    const p = node('button', `${label(m.name)} `, 'cat-pill');
    p.type = 'button';
    p.title = m.expression;
    p.onclick = () => {
      if (current) explain(m.name);
      else $('question').value = lang === 'zh' ? `按国家统计${label(m.name)}` : `Show ${m.name} by country`;
    };
    mRow.append(p);
  }
  const dRow = node('div', '', 'catalog-row');
  dRow.append(node('span', t('Dimensions & Time Grains:', '支持维度与时间粒度：'), 'catalog-title'));
  for (const d of catalog.dimensions.filter(x => !x.is_time)) {
    dRow.append(node('span', `${label(d.name)} (${d.name})`, 'cat-pill dim'));
  }
  for (const g of ['day', 'week', 'month']) {
    dRow.append(node('span', `${label(g)} (${g})`, 'cat-pill dim'));
  }
  strip.append(mRow, dRow);
}

function renderCurrent() {
  if (!current) return;
  const p = current.logical_plan, q = current.semantic_query;
  $('inspection-state').textContent = planOnly ? t('Planned · not executed', '仅规划 · 未执行') : t('Executed', '已编译并执行');
  const summaryText = `${current.dialect.toUpperCase()} · ${p.branches.length} ${t('fact branch(es)', '个独立事实表聚合分支')} (${p.strategy}) · ${q.time_grain ? t('Time grain: ', '时间粒度：') + label(q.time_grain) : t('No time grouping', '无时间分组')}`;
  $('inspection-summary').textContent = summaryText;

  if ($('active-query-bar')) {
    $('active-query-bar').hidden = false;
    $('active-query-bar').replaceChildren();
    const dimsText = q.dimensions.length ? q.dimensions.map(label).join(', ') : t('None (Grand Total)', '无（全局汇总）');
    const filterEntries = Object.entries(q.filters || {});
    const filterText = filterEntries.length ? filterEntries.map(([k, v]) => `${label(k)}=${Array.isArray(v) ? v.join(',') : v}`).join(' · ') : t('All data', '全量数据');
    const dateText = (q.date_from || q.date_to) ? ` (${q.date_from || '…'} ~ ${q.date_to || '…'})` : '';
    $('active-query-bar').append(
      node('span', `${t('Metrics:', '当前指标：')} ${q.metrics.map(label).join('、')}  |  ${t('Dimensions:', '分组维度：')} ${dimsText}  |  ${t('Filters:', '筛选范围：')} ${filterText}${dateText}`),
      node('span', summaryText, 'badge')
    );
  }

  $('branches').replaceChildren();
  for (const b of p.branches) {
    const c = node('article', '', 'branch');
    c.append(node('h3', `${t('Fact Table:', '事实表分支：')} ${b.root_dataset}`), node('p', t('Physical table: ', '物理表：') + b.root_table, 'hint'));
    for (const d of b.dimensions) {
      c.append(node('p', `${d.dataset}.${d.column} → ${d.time_grain ? label(d.time_grain) + ' ' : ''}${label(d.name)}`, 'time-mapping'));
    }
    for (const j of b.joins) {
      c.append(node('p', `LEFT JOIN: ${j.left_dataset} → ${j.right_dataset} (${t('many-to-one safe', '多对一防扇出')})`, 'hint'));
    }
    c.append(node('p', t('Predicates: ', '过滤条件：') + (b.predicates.length ? JSON.stringify(b.predicates) : t('None', '无')), 'hint'));
    for (const m of b.metrics) {
      c.append(button(label(m.name), () => explain(m.name)), node('code', m.expression));
    }
    $('branches').append(c);
  }

  $('merge-summary').hidden = false;
  $('merge-summary').textContent = p.strategy === 'aggregate_then_join'
    ? t('Multi-fact protection: Each fact table is aggregated in its own CTE first, then aligned by group keys via UNION + LEFT JOIN so bet and deposit amounts never multiply each other.',
        '多事实表防扇出保护：bets（投注）与 deposits（充值）在各自的 CTE 分支中先按维度独立聚合，再通过 UNION 分组键 + LEFT JOIN 对齐，彻底杜绝多对多明细 JOIN 导致的金额翻倍。')
    : t('Single-fact aggregation: Aggregated directly at the requested dimension grain.',
        '单事实表聚合：直接在请求的维度粒度上进行安全聚合。');
  if (q.time_grain) {
    $('merge-summary').textContent += t(' Periods use ISO start dates; weeks start Monday. Date filters apply before grouping.',
      ' 时间周期统一采用起始日期（周粒度以周一为起点），日期范围过滤在分组聚合前生效。');
  }

  $('semantic').textContent = JSON.stringify(q, null, 2);
  $('logical').textContent = JSON.stringify(p, null, 2);
  $('sql').textContent = current.sql + '\n\n-- Bound Parameters:\n' + JSON.stringify(current.parameters);

  if (planOnly) {
    $('results').textContent = t('Plan compiled only. Database was not queried.', '仅编译了执行计划与 SQL，未执行数据库查询。');
  } else {
    table($('results'), current.rows, true);
  }

  $('breadcrumbs').replaceChildren();
  if ($('breadcrumbs-wrap')) $('breadcrumbs-wrap').hidden = history.length <= 1;
  history.forEach((r, i) => {
    const dimNames = r.semantic_query.dimensions.map(label).join(', ') || (r.semantic_query.time_grain ? label(r.semantic_query.time_grain) : t('Total', '汇总'));
    const filterSummary = Object.entries(r.semantic_query.filters || {}).map(([k, v]) => `${label(k)}=${v}`).join(',');
    const stepLabel = `${i + 1}. ${dimNames}${filterSummary ? ` (${filterSummary})` : ''}`;
    $('breadcrumbs').append(button(stepLabel, () => {
      current = r;
      history = history.slice(0, i + 1);
      metricResult = null;
      $('metric-panel').hidden = true;
      selected = null;
      $('drill-controls').hidden = true;
      renderCurrent();
    }, i === history.length - 1 ? 'example selected' : 'example'));
  });

  $('export').disabled = planOnly;
  $('sandbox-empty').hidden = true;
  fillSelect($('change-metric'), q.metrics);
  setCandidate();
}

async function chooseDrill(row) {
  await action(async () => {
    selected = {};
    for (const d of current.logical_plan.dimensions) {
      if (row[d.name] != null) selected[d.name] = String(row[d.name]);
    }
    if (current.logical_plan.dimensions.some(d => row[d.name] == null)) {
      throw new Error(t('NULL groups cannot be drilled with equality filters.', 'NULL 分组暂不支持等值下钻。'));
    }
    const opts = await post('/api/drill/options', query());
    $('drill-targets').replaceChildren();
    if ($('drill-selection-badge')) {
      const selText = Object.entries(selected).map(([k, v]) => `${label(k)}: ${fmt(v)}`).join(' · ');
      $('drill-selection-badge').textContent = selText || t('All rows', '当前总计行');
    }
    for (const opt of opts) {
      if (opt.available) {
        $('drill-targets').append(button(`↘ ${t('Drill into ', '下钻至：')}${label(opt.dimension)}`, () => drill(opt.dimension), 'primary-btn small-btn'));
      } else {
        $('drill-targets').append(node('p', `🚫 ${label(opt.dimension)} — ${t('Incompatible with selected metrics (no safe JOIN path)', '与当前所选指标不兼容（无安全多对一关联路径）')}`, 'hint'));
      }
    }
    $('drill-controls').hidden = false;
    $('drill-controls').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    $('status').textContent = t('Select a target dimension below the table to drill down.', '请在表格下方选择要下钻的目标维度。');
  });
}

async function drill(target) {
  await action(async () => {
    const result = await post('/api/drill', { query: query(), selection: selected, target });
    current = result;
    history.push(result);
    metricResult = null;
    $('metric-panel').hidden = true;
    planOnly = false;
    $('drill-controls').hidden = true;
    renderCurrent();
    $('status').textContent = t('Drill-down complete', '下钻完成，上方可点击面包屑回退');
  });
}

async function explain(metric, row = null) {
  await action(async () => {
    metricResult = { data: await post('/api/metrics/explain', { query: query(), metric }), row };
    activateTab('explore');
    renderMetric();
    $('metric-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    $('status').textContent = t('Metric lineage displayed below the results.', '已在结果下方展开指标口径与分子分母拆解。');
  });
}

function renderMetric() {
  if (!metricResult) return;
  const { data: d, row } = metricResult, e = $('metric-content');
  e.replaceChildren();
  $('metric-panel').hidden = false;
  e.append(
    node('h3', `${label(d.name)} (${d.name})`),
    node('code', `${t('YAML Formula:', 'YAML 定义公式：')} ${d.formula}`),
    node('p', `${t('Fact Table:', '所属事实表：')} ${d.source}  |  ${t('Referenced Columns:', '引用字段：')} ${d.columns.join(', ')}  |  ${t('Time Dimension:', '时间维度字段：')} ${d.time_fields.join(', ')}`)
  );
  for (const a of d.aggregates) {
    e.append(node('p', `• ${a.function}(${a.columns.join(', ')}) — ${a.distinct ? t('DISTINCT: each unique player_id counts once per group.', '去重聚合：同一分组内每个玩家 ID 仅计一次（不可跨维度直接相加）。') : t('Additive within group.', '分组内常规聚合。')}`, 'hint'));
  }
  if (d.ratio) {
    e.append(node('p', t('Ratio Metric: Recomputed per group as Numerator ÷ Denominator (safe NULLIF division). Below are the live numerator and denominator values:', '比率型指标：在每个分组内按「分子 ÷ 分母」实时重算（自带 NULLIF 防除零保护）。当前选中分组的真实分子与分母如下：')));
  }
  if (d.components) {
    const section = node('div', '');
    const rows = row ? d.components.filter(r => current.logical_plan.dimensions.every(dim => r[dim.name] === row[dim.name])) : d.components;
    table(section, rows);
    e.append(section);
  }
  jsonDetails(e, { scope: d.scope, model_fingerprint: d.model_fingerprint, evidence: d.evidence });
}

function fillSelect(el, values) {
  const old = el.value;
  el.replaceChildren();
  for (const v of values) {
    const o = node('option', label(v));
    o.value = v;
    el.append(o);
  }
  if (values.includes(old)) el.value = old;
}

function setCandidate() {
  const m = current?.metric_details.find(m => m.name === $('change-metric').value);
  $('candidate').value = m?.formula || '';
}

if ($('sandbox-preset')) {
  $('sandbox-preset').onchange = () => {
    if ($('sandbox-preset').value) $('candidate').value = $('sandbox-preset').value;
  };
}

function renderPeriod() {
  if (!periodResult) return;
  const r = periodResult, e = $('period-result');
  e.replaceChildren();
  e.append(
    node('p', `${t('Previous Period:', '基期范围：')} ${r.previous_period.start} ~ ${r.previous_period.end}   vs   ${t('Current Period:', '当期范围：')} ${r.current_period.start} ~ ${r.current_period.end}`, 'badge'),
    node('h3', `${t('Total:', '总计变化：')} ${fmt(r.previous)} → ${fmt(r.current)} · Δ ${fmt(r.delta)} (${r.change_pct == null ? t('rate unavailable', '变化率不适用') : fmt(r.change_pct) + '%'})`)
  );
  const div = node('div', '');
  table(div, r.rows);
  e.append(
    div,
    node('p', t('Remaining groups Δ (outside Top N): ', '其余未展开分组变化量汇总：') + fmt(r.other_delta)),
    node('p', t('Note: Contribution % = Group Δ / Total Net Δ. Describes mathematical composition, not causal attribution.', '说明：净变化贡献率 = 该分组变化量 ÷ 总净变化量（可能为负或超过 100%），用于描述算术构成而非业务因果归因。'), 'hint')
  );
  jsonDetails(e, r.evidence);
}

function renderModel() {
  if (!modelResult) return;
  const r = modelResult, e = $('model-result');
  e.replaceChildren();
  e.append(node('p', `${t('Saved Formula:', '原模型公式：')} ${r.old_expression}   →   ${t('Candidate Formula:', '候选公式：')} ${r.candidate_expression}`, 'badge'));
  const div = node('div', '');
  table(div, r.rows);
  e.append(div, node('p', t('Shadow evaluation only · models/gaming.yaml was not modified.', '仅在内存事务快照中完成沙箱对比 · 磁盘上的 models/gaming.yaml 未被修改。'), 'hint'));
  jsonDetails(e, { old_fingerprint: r.old_fingerprint, candidate_fingerprint: r.candidate_fingerprint, evidence: r.evidence });
}

async function loadData() {
  try {
    const r = await fetch('/api/data');
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail);
    $('db-meta').textContent = `${t('Active Engine:', '当前数据库引擎：')} ${data.backend.toUpperCase()} · ${t('Click a table below to preview raw rows:', '点击下方表名预览真实明细数据：')}`;
    $('tables').replaceChildren();
    for (const x of data.tables) {
      const b = button(`${x.name} (${x.row_count} ${t('rows', '行')})`, () => showTable(x.name), x.name === activeTable ? 'tab selected' : 'tab');
      $('tables').append(b);
    }
    await showTable(activeTable);
  } catch (e) {
    $('preview').textContent = e.message;
  }
}

async function showTable(name) {
  activeTable = name;
  Array.from($('tables').children).forEach(btn => {
    btn.classList.toggle('selected', btn.textContent.startsWith(name + ' '));
  });
  try {
    const r = await fetch('/api/data/preview?table=' + encodeURIComponent(name) + '&limit=40');
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail);
    table($('preview'), d.rows);
  } catch (e) {
    $('preview').textContent = e.message;
  }
}

function translate() {
  // Translate the default prompt without overwriting a user's own question.
  if (!$('question').value.trim() || Object.values(defaultQuestions).includes($('question').value)) {
    $('question').value = defaultQuestions[lang];
  }
  $('status').textContent = '';
  $('drill-controls').hidden = true;
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  $('language').value = lang;
  document.querySelectorAll('[data-en]').forEach(e => e.textContent = e.dataset[lang]);

  $('examples').replaceChildren();
  const examples = [
    [
      '12 Countries · Multi-Fact & Ratio',
      '各国投注与充值',
      'rules',
      lang === 'zh' ? '按国家统计总投注额、总充值额、投注人数和人均投注额' : 'Show total stake, total deposit, unique bettors and stake per bettor by country',
      { metrics: ['total_stake', 'total_deposit', 'unique_bettors', 'stake_per_bettor'], dimensions: ['country'] }
    ],
    [
      'Monthly Trend',
      '月度趋势',
      'rules',
      lang === 'zh' ? '按月统计总投注额和总充值额' : 'Show total stake and total deposit by month',
      { metrics: ['total_stake', 'total_deposit'], time_grain: 'month' }
    ],
    [
      'Stake & NGR by Country',
      '国家与游戏类别',
      'rules',
      lang === 'zh' ? '按国家统计总投注额、净收入和人均投注额' : 'Show total stake, net gaming revenue and stake per bettor by country',
      { metrics: ['total_stake', 'ngr', 'stake_per_bettor'], dimensions: ['country'] }
    ],
    [
      'Top 5 Countries in Last 30 Days',
      '最近30天总投注额前5国家',
      'rules',
      lang === 'zh' ? '最近30天总投注额前5国家' : 'Show top 5 countries by total stake in the last 30 days',
      { metrics: ['total_stake'], dimensions: ['country'], order_by: [{ field: 'total_stake', direction: 'desc' }], limit: 5 }
    ],
    [
      'US + Japan + Singapore Monthly',
      '美国、日本与新加坡按月投注对比',
      'structured',
      '',
      { metrics: ['total_stake', 'unique_bettors', 'stake_per_bettor'], time_grain: 'month', filters: { country: ['US', 'JP', 'SG'] } }
    ]
  ];

  for (const [en, zh, modeVal, qText, qJson] of examples) {
    $('examples').append(button(t(en, zh), () => {
      $('mode').value = modeVal;
      switchMode();
      if (modeVal === 'structured') {
        $('structured').value = JSON.stringify(qJson, null, 2);
      } else {
        $('question').value = qText;
        $('structured').value = JSON.stringify(qJson, null, 2);
      }
      run();
    }, 'example'));
  }

  if (catalog) {
    renderCatalogStrip();
    fillSelect($('period-metric'), catalog.metrics.filter(m => m.additive).map(m => m.name));
    fillSelect($('period-dimension'), catalog.dimensions.filter(d => !d.is_time).map(d => d.name));
  }
  if (current) {
    const candidate = $('candidate').value;
    renderCurrent();
    $('candidate').value = candidate;
  }
  renderPeriod();
  renderModel();
  renderMetric();
}

$('language').onchange = () => { lang = $('language').value; localStorage.setItem('ossie-language', lang); translate(); };
$('mode').onchange = switchMode;
$('run').onclick = () => run();
$('plan-only').onclick = () => run(true);
$('close-metric').onclick = () => { $('metric-panel').hidden = true; metricResult = null; };
$('change-metric').onchange = setCandidate;

$('compare-period').onclick = () => action(async () => {
  periodResult = null;
  const body = { metric: $('period-metric').value, dimension: $('period-dimension').value, filters: query().filters || {}, top_n: Number($('top-n').value) };
  const dates = ['previous-start', 'previous-end', 'current-start', 'current-end'].map(id => $(id).value);
  if (dates.some(Boolean)) {
    if (!dates.every(Boolean)) throw new Error(t('Fill all four dates or leave all blank.', '请填写全部四个日期，或全部留空以默认对比最近两个完整月。'));
    body.previous = { start: dates[0], end: dates[1] };
    body.current = { start: dates[2], end: dates[3] };
  }
  periodResult = await post('/api/compare/periods', body);
  renderPeriod();
}, $('period-result'));

$('compare-model').onclick = () => action(async () => {
  modelResult = null;
  modelResult = await post('/api/compare/model', { query: query(), metric: $('change-metric').value, expression: $('candidate').value });
  renderModel();
}, $('model-result'));

$('export').onclick = () => action(async () => {
  const blob = await post('/api/export', query(), true), url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = 'query-reproduction.zip'; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  $('status').textContent = t('Reproduction package exported.', '查询复现包 (.zip) 已导出。');
});

$('reset').onclick = async () => {
  if (confirm(t('Rebuild demo DuckDB warehouse with the 36-player multi-country dataset?', '确认将示例数据库重置为包含 12 个国家、36 名玩家的初始数据集？'))) {
    let resetDone = false;
    await action(async () => {
      await post('/api/data/seed', {});
      clear();
      await loadData();
      resetDone = true;
      $('status').textContent = t('Demo data reset.', '示例数据已重置。');
    });
    if (resetDone) await run();
  }
};

const presets = {
  openai: ['', 'gpt-4o-mini'],
  deepseek: ['https://api.deepseek.com/v1', 'deepseek-chat'],
  qwen: ['https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus'],
  ollama: ['http://127.0.0.1:11434/v1', 'llama3.2'],
  openrouter: ['https://openrouter.ai/api/v1', 'openai/gpt-4o-mini']
};
$('provider-preset').onchange = () => {
  const p = presets[$('provider-preset').value];
  if (p) { $('base-url').value = p[0]; $('model').value = p[1]; }
};

$('compare-model').disabled = true;
activateTab('explore');
translate();
switchMode();
fetch('/api/model').then(r => r.json()).then(async d => {
  catalog = d;
  translate();
  $('results').textContent = t('Enter a question and run a query to see results.', '输入问题并执行查询，即可查看结果。');
  await loadData();
}).catch(e => {
  $('status').textContent = e.message;
  loadData();
});
