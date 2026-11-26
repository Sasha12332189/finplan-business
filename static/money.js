/* Stage 2: subscription (Telegram Stars), soft locks, Reports screen, invoices, debts, income book. */
(function(){
'use strict';
const F = window.FB, {S, esc, icon, $, $$, api, post, money, fmtDate, toast, openSheet, closeSheet, errorToast, can, opts} = F;
const tg = window.Telegram && Telegram.WebApp;
const L = () => F.lang();
const W = {
  uk:{tryPro:'Спробувати 14 днів Pro',proUntil:'до {d}',trialUntil:'Пробний Pro до {d}',free:'Безкоштовний тариф',freeSub:'Аналітика за 2 місяці, 10 запитів до ШІ',
    plans:'Тарифи',month:'Місяць',year:'Рік',save27:'−27%',connect:'Підключити за {n} ⭐',current:'Ваш тариф',perMonth:'/ міс',perYear:'/ рік',
    autoRenew:'Автопродовження',cancelSub:'Скасувати продовження',resumeSub:'Відновити продовження',ownerOnly:'Підписку оформлює власник бізнесу.',
    paidOk:'Оплату отримано! Оновлюю…',locked:'Доступно в {p}',unlock:'Відкрити {p}',
    f_history:'Уся історія та порівняння',f_reports:'Excel і PDF звіти, авто 1-го числа',f_ai:'ШІ-асистент: {n} запитів / міс',f_media:'Фото чеків і голосові',
    f_banks:'Імпорт monobank',f_forecast:'Прогноз і касовий розрив',f_invoices:'Рахунки без ліміту + PDF',f_acc:'+ бухгалтер (лише перегляд)',
    f_team:'Команда до 10 людей, ролі',f_stock:'Склад і собівартість продажів',f_allpro:'Усе з Pro',freeNote:'Свої записи ви бачите й вивантажуєте завжди — CSV доступний і у Free.',
    pnl:'P&L',cogs:'Собівартість',gross:'Валовий прибуток',opex:'Операційні витрати',net:'Прибуток',cashflow:'Грошовий потік по місяцях',
    byCat:'За категоріями',byClient:'Топ клієнтів',byProject:'За проєктами',byMember:'За працівниками',compare:'Порівняння з минулим періодом',
    excel:'Excel',pdf:'PDF-звіт',csv:'CSV',sentToChat:'Файл надіслано в чат бота',prev_month:'Минулий місяць',custom:'Свій період',
    invoices:'Рахунки',debts:'Борги',book:'Книга доходів',newInvoice:'Новий рахунок',items:'Позиції',itemName:'Назва',qty:'К-сть',price:'Ціна',
    addItem:'+ позиція',dueDate:'Сплатити до',st_draft:'Чернетка',st_sent:'Надіслано',st_paid:'Сплачено',st_overdue:'Прострочено',st_cancelled:'Скасовано',
    send:'Надіслати в чат',markPaid:'Сплачено',remind:'Нагадати клієнту',cancelInv:'Скасувати',theyOwe:'Вам винні',weOwe:'Ви винні',newDebt:'Новий борг',
    direction:'Хто винен',close:'Закрити борг',recordOp:'Записати як операцію',noInvoices:'Рахунків ще немає.',noDebts:'Боргів немає.',
    bookHint:'Дохід по днях для книги обліку доходів ФОП. Повна книга — у Excel-звіті.',quarter:'Квартал',none:'—',edit:'Редагувати',noClient:'Без клієнта',limitFree:'У Free — 5 рахунків на місяць'},
  ru:{tryPro:'Попробовать 14 дней Pro',proUntil:'до {d}',trialUntil:'Пробный Pro до {d}',free:'Бесплатный тариф',freeSub:'Аналитика за 2 месяца, 10 запросов к ИИ',
    plans:'Тарифы',month:'Месяц',year:'Год',save27:'−27%',connect:'Подключить за {n} ⭐',current:'Ваш тариф',perMonth:'/ мес',perYear:'/ год',
    autoRenew:'Автопродление',cancelSub:'Отменить продление',resumeSub:'Возобновить продление',ownerOnly:'Подписку оформляет владелец бизнеса.',
    paidOk:'Оплата получена! Обновляю…',locked:'Доступно в {p}',unlock:'Открыть {p}',
    f_history:'Вся история и сравнение',f_reports:'Excel и PDF отчёты, авто 1-го числа',f_ai:'ИИ-ассистент: {n} запросов / мес',f_media:'Фото чеков и голосовые',
    f_banks:'Импорт monobank',f_forecast:'Прогноз и кассовый разрыв',f_invoices:'Счета без лимита + PDF',f_acc:'+ бухгалтер (только просмотр)',
    f_team:'Команда до 10 человек, роли',f_stock:'Склад и себестоимость продаж',f_allpro:'Всё из Pro',freeNote:'Свои записи вы видите и выгружаете всегда — CSV доступен и в Free.',
    pnl:'P&L',cogs:'Себестоимость',gross:'Валовая прибыль',opex:'Операционные расходы',net:'Прибыль',cashflow:'Денежный поток по месяцам',
    byCat:'По категориям',byClient:'Топ клиентов',byProject:'По проектам',byMember:'По сотрудникам',compare:'Сравнение с прошлым периодом',
    excel:'Excel',pdf:'PDF-отчёт',csv:'CSV',sentToChat:'Файл отправлен в чат бота',prev_month:'Прошлый месяц',custom:'Свой период',
    invoices:'Счета',debts:'Долги',book:'Книга доходов',newInvoice:'Новый счёт',items:'Позиции',itemName:'Название',qty:'Кол-во',price:'Цена',
    addItem:'+ позиция',dueDate:'Оплатить до',st_draft:'Черновик',st_sent:'Отправлен',st_paid:'Оплачен',st_overdue:'Просрочен',st_cancelled:'Отменён',
    send:'Отправить в чат',markPaid:'Оплачен',remind:'Напомнить клиенту',cancelInv:'Отменить',theyOwe:'Вам должны',weOwe:'Вы должны',newDebt:'Новый долг',
    direction:'Кто должен',close:'Закрыть долг',recordOp:'Записать как операцию',noInvoices:'Счетов пока нет.',noDebts:'Долгов нет.',
    bookHint:'Доход по дням для книги учёта доходов ФОП. Полная книга — в Excel-отчёте.',quarter:'Квартал',none:'—',edit:'Изменить',noClient:'Без клиента',limitFree:'В Free — 5 счетов в месяц'},
};
W.en = Object.assign({}, W.uk, {edit:'Edit',noClient:'No client',tryPro:'Try Pro free for 14 days',free:'Free plan',plans:'Plans',month:'Month',year:'Year',current:'Your plan',
  connect:'Get it for {n} ⭐',invoices:'Invoices',debts:'Debts',book:'Income book',excel:'Excel',pdf:'PDF report',sentToChat:'The file is in the bot chat'});
const w = (k, v) => { let s = (W[L()] || W.uk)[k] || W.uk[k] || k; if (v) for (const [a, b] of Object.entries(v)) s = s.replace('{' + a + '}', b); return s; };
const PLAN_NAME = {pro:'Pro', team:'Team', free:'Free'};
const fmtDT = d => d ? new Date(d.endsWith('Z') ? d : d + 'Z').toLocaleDateString({uk:'uk-UA', ru:'ru-RU', en:'en-GB'}[L()], {day:'numeric', month:'long'}) : '';

/* ------------------------------------------------------------------ subscription */
F.planCard = function(){
  const p = S.me.plan;
  let title, sub, cta = '';
  if (p.paid_plan) { title = `finplan Business ${PLAN_NAME[p.paid_plan]}`; sub = w('proUntil', {d: fmtDT(p.until)}) + (p.auto_renew ? ' · ' + w('autoRenew') : ''); }
  else if (p.trial) { title = `finplan Business Pro`; sub = w('trialUntil', {d: fmtDT(p.trial_until)}); cta = w('plans'); }
  else if (p.is_admin) { title = 'finplan Business Team'; sub = 'admin'; }
  else { title = w('free'); sub = w('freeSub'); cta = p.trial_available ? w('tryPro') : w('plans'); }
  return `<button class="card plan-card" id="plan-card" type="button"><span class="pi">${icon('star')}</span><span class="grow"><b>${esc(title)}</b><small>${esc(sub)}</small></span>${cta ? `<span class="pill warn">${esc(cta)}</span>` : icon('chev', 'i chev')}</button>`;
};

function features(plan){
  const l = S.me.plan.plans[plan];
  if (plan === 'pro') return [w('f_history'), w('f_reports'), w('f_ai', {n: l.ai_requests}), w('f_media'), w('f_banks'), w('f_forecast'), w('f_invoices'), w('f_acc')];
  return [w('f_allpro'), w('f_team'), w('f_stock'), w('f_ai', {n: l.ai_requests})];
}

F.planSheet = function(reason){
  const p = S.me.plan;
  let period = 'month';
  const billing = can('billing');
  const render = el => {
    const tiers = ['pro', 'team'].map(plan => {
      const price = p.prices[plan][period];
      const isCur = p.paid_plan === plan;
      return `<div class="tier${plan === (reason && reason.plan_needed) || (!reason && plan === 'pro') ? ' sel' : ''}">
        <div class="tier-head"><b>${PLAN_NAME[plan]}</b><strong>${price.toLocaleString()} ⭐ <small class="muted">${period === 'month' ? w('perMonth') : w('perYear')}</small></strong></div>
        <ul>${features(plan).map(f => `<li>${icon('check')}<span>${esc(f)}</span></li>`).join('')}</ul>
        ${billing ? `<button class="btn ${plan === 'pro' ? 'pro' : ''}" style="margin-top:12px" data-buy="${plan}" ${isCur && p.period === period ? 'disabled' : ''}>${isCur && p.period === period ? w('current') : w('connect', {n: price.toLocaleString()})}</button>` : ''}
      </div>`;
    }).join('');
    const manage = p.can_manage && billing ? `<button class="btn ghost" id="renew" style="margin-top:12px">${p.auto_renew ? w('cancelSub') : w('resumeSub')}</button>` : '';
    el.innerHTML = `<h2>${w('plans')}<button class="icon-btn" id="x">${icon('x')}</button></h2>
      ${reason ? `<div class="pill warn" style="display:block;padding:10px 12px;border-radius:14px;margin-bottom:12px;font-size:12.5px">${icon('lock', 'i')} ${esc(w('locked', {p: PLAN_NAME[reason.plan_needed] || 'Pro'}))}</div>` : ''}
      <div class="seg"><button type="button" data-per="month" class="${period === 'month' ? 'on' : ''}">${w('month')}</button><button type="button" data-per="year" class="${period === 'year' ? 'on' : ''}">${w('year')} <span class="pos">${w('save27')}</span></button></div>
      <div class="tiers">${tiers}</div>${manage}
      ${billing ? '' : `<p class="hint">${w('ownerOnly')}</p>`}
      <p class="hint">${w('freeNote')}</p><p class="hint">/terms · /paysupport</p>`;
    $('#x', el).onclick = closeSheet;
    $$('[data-per]', el).forEach(b => b.onclick = () => { period = b.dataset.per; render(el); });
    $$('[data-buy]', el).forEach(b => b.onclick = () => buy(b.dataset.buy, period, b));
    const r = $('#renew', el); if (r) r.onclick = async () => { try { S.me.plan = await post(p.auto_renew ? '/plan/cancel' : '/plan/resume'); closeSheet(); toast('OK'); F.go('more'); } catch (e) { errorToast(e); } };
  };
  openSheet('<div id="plans"></div>', el => render($('#plans', el)));
};

async function buy(plan, period, btn){
  btn.disabled = true;
  try {
    const {link} = await post('/plan/invoice', {plan, period});
    if (tg && tg.openInvoice) {
      tg.openInvoice(link, async status => {
        btn.disabled = false;
        if (status === 'paid') { toast(w('paidOk')); closeSheet(); setTimeout(F.boot, 1500); }
      });
    } else { window.open(link, '_blank'); btn.disabled = false; }
  } catch (e) { btn.disabled = false; errorToast(e); }
}

F.onPlanRequired = detail => { if (S.me && S.me.plan) F.planSheet(detail); };
F.lockedCard = detail => `<div class="card locked"><div class="blur"><div class="kpis"><div class="card kpi"><span>—</span><strong>123 456 ₴</strong></div><div class="card kpi"><span>—</span><strong>45 678 ₴</strong></div></div>${F.chartSVG([{date:'2026-01-01',income:3,expense:1},{date:'2026-01-02',income:5,expense:2},{date:'2026-01-03',income:4,expense:3},{date:'2026-01-04',income:6,expense:2}], 'day')}</div>
  <div class="unlock">${icon('lock')}<b>${esc(w('locked', {p: PLAN_NAME[(detail && detail.plan_needed) || 'pro']}))}</b><button class="btn pro" style="width:auto;padding:10px 18px" onclick="FB.planSheet(${esc(JSON.stringify(detail || {}))})">${esc(w('unlock', {p: PLAN_NAME[(detail && detail.plan_needed) || 'pro']}))}</button></div></div>`;
const baseAfterMore = F.afterMore;
F.afterMore = v => { const c = $('#plan-card', v); if (c) c.onclick = () => F.planSheet(); baseAfterMore && baseAfterMore(v); };

/* ------------------------------------------------------------------ reports */
const RP = ['month', 'prev_month', 'quarter', 'year'];
const RL = p => p === 'prev_month' ? w('prev_month') : F.t(p);
function bars(items, color){
  if (!items || !items.length) return `<div class="empty" style="padding:8px">—</div>`;
  const max = Math.max(...items.map(i => Number(i.amount)));
  return items.slice(0, 8).map(i => `<div style="margin:9px 0"><div style="display:flex;justify-content:space-between;gap:8px;font-size:13px"><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(i.name)}</span><b style="white-space:nowrap">${money(i.amount)} <span class="muted small">${i.share.toFixed(0)}%</span></b></div><div class="progress" style="margin-top:5px;height:6px"><i style="width:${(Number(i.amount) / max * 100).toFixed(1)}%;background:${color}"></i></div></div>`).join('');
}
F.TABS.reports = async function(){
  const v = $('#view');
  S.rPeriod = S.rPeriod || 'month';
  if (!can('read')) { v.innerHTML = `<h1>${F.t('tabReports')}</h1><div class="card empty">${icon('lock')}</div>`; return; }
  v.innerHTML = `<h1>${F.t('tabReports')}</h1><div class="chips">${RP.map(p => `<button class="chip${p === S.rPeriod ? ' on' : ''}" data-rp="${p}">${RL(p)}</button>`).join('')}</div><div id="rbody"><div class="card" style="height:260px"></div></div>`;
  $$('[data-rp]', v).forEach(b => b.onclick = () => { S.rPeriod = b.dataset.rp; F.TABS.reports(); });
  const box = $('#rbody');
  let d;
  try { d = await api('/reports?period=' + S.rPeriod); }
  catch (e) { if (e.status === 402) { box.innerHTML = F.lockedCard(e.detail); return; } return errorToast(e); }
  const s = d.summary, pro = S.me.plan.limits.reports;
  const lock = pro ? '' : ` <span class="lock">${icon('lock')}</span>`;
  const pnl = d.pnl;
  const prow = (l, v, b) => `<tr><td${b ? ' style="font-weight:750"' : ''}>${l}</td><td class="r${b ? '' : ''}" style="${b ? 'font-weight:750' : ''}">${money(v)}</td></tr>`;
  const cmp = d.previous ? `<div class="card"><div class="card-title"><span>${w('compare')}</span><span>${fmtDate(d.previous_start)} – ${fmtDate(d.previous_end)}</span></div><table class="table"><tbody>
     ${[['revenue', true], ['expenses', false], ['profit', true]].map(([k, up]) => `<tr><td>${F.t(k)}</td><td class="r muted">${money(d.previous[k])}</td><td class="r"><b>${money(s[k])}</b></td><td class="r">${F.delta(d.change[k], up).replace(F.t('vsPrev'), '')}</td></tr>`).join('')}</tbody></table></div>` : '';
  box.innerHTML = `
    <div class="card"><div class="card-title"><span>${w('pnl')}</span><span>${fmtDate(d.start)} – ${fmtDate(d.end)}</span></div>
      <table class="table"><tbody>${prow(F.t('revenue'), pnl.revenue)}${prow('− ' + w('cogs'), -pnl.cogs)}${prow(w('gross'), pnl.gross_profit, 1)}${prow('− ' + w('opex'), -pnl.operating)}${prow(w('net'), pnl.profit, 1)}</tbody></table>
      <div class="grid2" style="margin-top:10px"><div class="small muted">${F.t('margin')}: <b style="color:var(--ink)">${s.margin === null ? '—' : s.margin + '%'}</b></div><div class="small muted" style="text-align:right">${F.t('avgCheck')}: <b style="color:var(--ink)">${s.avg_check ? money(s.avg_check) : '—'}</b></div></div></div>
    ${cmp}
    <div class="card"><div class="card-title"><span>${w('cashflow')}</span></div>${F.chartSVG(d.cashflow, 'month')}<div class="legend"><span><i style="background:var(--primary)"></i>${F.t('revenue')}</span><span><i style="background:var(--expense)"></i>${F.t('expenses')}</span></div></div>
    <div class="card"><div class="card-title"><span>${w('byCat')} · ${F.t('expenses')}</span></div>${bars(d.expense_by_category, 'var(--expense)')}</div>
    <div class="card"><div class="card-title"><span>${w('byCat')} · ${F.t('revenue')}</span></div>${bars(d.income_by_category, 'var(--primary)')}</div>
    <div class="card"><div class="card-title"><span>${w('byClient')}</span></div>${bars(d.by_client.map(x => x.id ? x : {...x, name: w('noClient')}), 'var(--primary-2)')}</div>
    ${d.by_project.some(x => x.id) ? `<div class="card"><div class="card-title"><span>${w('byProject')}</span></div>${bars(d.by_project, 'var(--chart-3)')}</div>` : ''}
    ${d.by_member.filter(x => x.id).length > 1 ? `<div class="card"><div class="card-title"><span>${w('byMember')}</span></div>${bars(d.by_member, 'var(--info)')}</div>` : ''}
    ${can('export') ? `<div class="btn-row"><button class="btn" data-send="excel">${icon('download')} ${w('excel')}${lock}</button><button class="btn ghost" data-send="pdf">${icon('doc')} ${w('pdf')}${lock}</button></div>
    <button class="btn ghost" style="margin-top:8px" data-send="csv">${icon('download')} ${w('csv')}</button>` : ''}`;
  $$('[data-send]', box).forEach(b => b.onclick = async () => {
    if (b.dataset.send !== 'csv' && !pro) return F.planSheet({plan_needed: 'pro', feature: 'reports'});
    b.disabled = true;
    try { await post('/reports/send', {kind: b.dataset.send, period: S.rPeriod}); toast(w('sentToChat')); }
    catch (e) { errorToast(e); } finally { b.disabled = false; }
  });
};

/* ------------------------------------------------------------------ documents */
F.docTabs = () => [['invoices', w('invoices')], ['debts', w('debts')], ['taxes', F.t('taxes')], ['book', w('book')]];
const stPill = s => `<span class="pill ${s === 'paid' ? 'ok' : s === 'overdue' ? 'bad' : s === 'sent' ? 'info' : ''}">${w('st_' + s)}</span>`;
F.docHandlers = {taxes: F.renderTaxes, invoices: renderInvoices, debts: renderDebts, book: renderBook};

async function renderInvoices(box){
  const rows = await api('/invoices');
  box.innerHTML = `${can('write') ? `<button class="btn" id="inv-new">${icon('plus')} ${w('newInvoice')}</button>` : ''}
    <div class="card" style="margin-top:12px">${rows.length ? rows.map(i => `<div class="row tap" data-inv="${i.id}"><span class="ic">${icon('doc')}</span><span class="grow"><b>№${i.number} ${esc(i.counterparty || '')}</b><small>${i.due_date ? w('dueDate') + ' ' + fmtDate(i.due_date) : ''}</small></span><span style="display:grid;justify-items:end;gap:4px"><span class="amt">${money(i.total, i.currency)}</span>${stPill(i.status)}</span></div>`).join('') : `<div class="empty">${w('noInvoices')}</div>`}</div>
    ${S.me.plan.plan === 'free' ? `<p class="hint">${w('limitFree')}</p>` : ''}`;
  const n = $('#inv-new', box); if (n) n.onclick = () => invoiceForm();
  $$('[data-inv]', box).forEach(r => r.onclick = () => invoiceSheet(rows.find(i => i.id === Number(r.dataset.inv)), box));
}

function invoiceForm(inv){
  const m = S.meta;
  const items = inv ? inv.items.map(i => ({...i})) : [{name:'', qty:1, price:''}];
  const due = inv && inv.due_date || new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  const html = `<h2>${inv ? '№' + inv.number : w('newInvoice')}<button class="icon-btn" id="x">${icon('x')}</button></h2><form id="invf">
    <label class="f">${F.t('client')}<select class="in" name="counterparty_id">${opts(m.counterparties, inv && inv.counterparty_id, w('none'))}</select></label>
    <div class="card-title" style="margin:4px 0 8px"><span>${w('items')}</span></div><div id="items"></div>
    <button type="button" class="link" id="add-item">${w('addItem')}</button>
    <div class="grid2" style="margin-top:8px"><label class="f">${w('dueDate')}<input class="in" type="date" name="due_date" value="${due}"></label><label class="f">${F.t('total')}<input class="in" id="inv-total" disabled></label></div>
    <label class="f">${F.t('note')}<input class="in" name="note" value="${esc(inv && inv.note || '')}"></label>
    <button class="btn" type="submit">${F.t('save')}</button></form>`;
  openSheet(html, el => {
    const list = $('#items', el), f = $('#invf', el);
    const draw = () => {
      list.innerHTML = items.map((it, k) => `<div style="display:grid;grid-template-columns:minmax(0,1fr) 56px 86px;gap:6px;margin-bottom:6px"><input class="in" placeholder="${w('itemName')}" data-k="${k}" data-f="name" value="${esc(it.name)}"><input class="in" inputmode="decimal" placeholder="${w('qty')}" data-k="${k}" data-f="qty" value="${it.qty}"><input class="in" inputmode="decimal" placeholder="${w('price')}" data-k="${k}" data-f="price" value="${it.price}"></div>`).join('');
      $$('[data-f]', list).forEach(i => i.oninput = () => { items[i.dataset.k][i.dataset.f] = i.value; total(); });
      total();
    };
    const total = () => { $('#inv-total', el).value = money(items.reduce((a, i) => a + (Number(String(i.qty).replace(',', '.')) || 0) * (Number(String(i.price).replace(',', '.')) || 0), 0)); };
    $('#add-item', el).onclick = () => { items.push({name:'', qty:1, price:''}); draw(); };
    $('#x', el).onclick = closeSheet;
    draw();
    f.onsubmit = async e => {
      e.preventDefault();
      const body = {counterparty_id: f.counterparty_id.value ? Number(f.counterparty_id.value) : null, due_date: f.due_date.value || null, note: f.note.value.trim() || null,
        items: items.filter(i => i.name.trim()).map(i => ({name: i.name.trim(), qty: String(i.qty).replace(',', '.') || '1', price: String(i.price).replace(',', '.') || '0'}))};
      try { inv ? await F.patch('/invoices/' + inv.id, body) : await post('/invoices', body); closeSheet(); toast(F.t('saved')); S.docsTab = 'invoices'; F.TABS.docs(); }
      catch (err) { errorToast(err); }
    };
  });
}

function invoiceSheet(inv, box){
  const pro = S.me.plan.limits.invoice_pdf;
  const act = (a, label, cls, needPro) => `<button class="btn ${cls || 'ghost'}" data-act="${a}" style="margin-top:8px">${label}${needPro && !pro ? ` <span class="lock">${icon('lock')}</span>` : ''}</button>`;
  const html = `<h2>№${inv.number} ${stPill(inv.status)}<button class="icon-btn" id="x">${icon('x')}</button></h2>
    <div class="card flat"><div class="row"><span class="grow"><b>${esc(inv.counterparty || '—')}</b><small>${inv.due_date ? w('dueDate') + ' ' + fmtDate(inv.due_date, {day:'numeric', month:'long', year:'numeric'}) : ''}</small></span><span class="amt">${money(inv.total, inv.currency)}</span></div>
    ${inv.items.map(i => `<div class="row"><span class="grow"><b>${esc(i.name)}</b><small>${i.qty} × ${money(i.price, inv.currency)}</small></span><span class="amt">${money(i.sum, inv.currency)}</span></div>`).join('')}</div>
    ${can('write') && inv.status !== 'paid' && inv.status !== 'cancelled' ? act('send', `${icon('send')} ${w('send')}`, '', false) + act('paid', `${icon('check')} ${w('markPaid')}`, 'ghost') + (inv.status !== 'draft' ? act('remind', w('remind'), 'ghost', true) : '') + `<div class="btn-row"><button class="btn ghost" data-edit>${w('edit')}</button><button class="btn danger" data-act="cancel">${w('cancelInv')}</button></div>` : ''}`;
  openSheet(html, el => {
    $('#x', el).onclick = closeSheet;
    const ed = $('[data-edit]', el); if (ed) ed.onclick = () => { closeSheet(); setTimeout(() => invoiceForm(inv), 260); };
    $$('[data-act]', el).forEach(b => b.onclick = async () => {
      if (b.dataset.act === 'remind' && !pro) return F.planSheet({plan_needed: 'pro'});
      b.disabled = true;
      try { await post(`/invoices/${inv.id}/${b.dataset.act}`, {}); closeSheet(); toast(b.dataset.act === 'paid' ? F.t('saved') : w('sentToChat')); renderInvoices(box); }
      catch (e) { b.disabled = false; errorToast(e); }
    });
  });
}

async function renderDebts(box){
  const d = await api('/debts');
  const open = d.items.filter(x => x.status === 'open');
  const row = x => `<div class="row tap" data-debt="${x.id}"><span class="ic ${x.direction === 'they_owe' ? 'in' : 'out'}">${icon('person')}</span><span class="grow"><b>${esc(x.counterparty || '—')}</b><small>${[x.note, x.due_date ? F.t('until') + ' ' + fmtDate(x.due_date) : ''].filter(Boolean).map(esc).join(' · ') || '&nbsp;'}</small></span><span class="amt">${money(x.amount)}</span></div>`;
  box.innerHTML = `<div class="kpis"><div class="card kpi"><span>${w('theyOwe')}</span><strong class="pos">${money(d.they_owe)}</strong></div><div class="card kpi"><span>${w('weOwe')}</span><strong class="neg">${money(d.we_owe)}</strong></div></div>
    ${can('write') ? `<button class="btn" id="debt-new" style="margin-top:12px">${icon('plus')} ${w('newDebt')}</button>` : ''}
    <div class="card" style="margin-top:12px">${open.length ? open.map(row).join('') : `<div class="empty">${w('noDebts')}</div>`}</div>`;
  const n = $('#debt-new', box); if (n) n.onclick = () => debtForm();
  $$('[data-debt]', box).forEach(r => r.onclick = () => { const x = d.items.find(i => i.id === Number(r.dataset.debt)); can('write') && debtSheet(x, box); });
  function debtForm(x){
    const m = S.meta;
    F.simpleForm(w('newDebt'), [
      {name:'direction', label:w('direction'), type:'select', options:[['they_owe', w('theyOwe')], ['we_owe', w('weOwe')]], value: x ? x.direction : 'they_owe'},
      {name:'counterparty_id', label:F.t('client'), type:'select', options:[['', w('none')]].concat(m.counterparties.map(c => [c.id, c.name])), value: x && x.counterparty_id},
      {name:'amount', label:F.t('amount'), mode:'decimal', value: x && x.amount}, {name:'due_date', label:F.t('until'), type:'date', value: x && x.due_date},
      {name:'note', label:F.t('note'), value: x && x.note}],
      body => { body.counterparty_id = body.counterparty_id ? Number(body.counterparty_id) : null; return x ? F.patch('/debts/' + x.id, body) : post('/debts', body); },
      x && (() => F.del('/debts/' + x.id)));
  }
  function debtSheet(x){
    openSheet(`<h2>${esc(x.counterparty || '—')}<button class="icon-btn" id="x">${icon('x')}</button></h2><div class="card flat"><div class="row"><span class="grow"><b>${x.direction === 'they_owe' ? w('theyOwe') : w('weOwe')}</b><small>${esc(x.note || '')}</small></span><span class="amt">${money(x.amount)}</span></div></div>
      <label class="switch" style="margin-top:10px"><span>${w('recordOp')}</span><input type="checkbox" id="rec" checked></label>
      <button class="btn" id="close-debt" style="margin-top:10px">${icon('check')} ${w('close')}</button><button class="btn ghost" id="edit-debt" style="margin-top:8px">${w('edit')}</button>`, el => {
      $('#x', el).onclick = closeSheet;
      $('#close-debt', el).onclick = async () => { try { await post(`/debts/${x.id}/close`, {record_operation: $('#rec', el).checked}); closeSheet(); toast(F.t('saved')); F.refresh(); } catch (e) { errorToast(e); } };
      $('#edit-debt', el).onclick = () => { closeSheet(); setTimeout(() => debtForm(x), 260); };
    });
  }
}

async function renderBook(box){
  const today = new Date(F.todayISO());
  S.bookQ = S.bookQ || `${today.getFullYear()}-${Math.floor(today.getMonth() / 3) + 1}`;
  const [y, q] = S.bookQ.split('-').map(Number);
  const from = `${y}-${String(3 * q - 2).padStart(2, '0')}-01`, toD = new Date(y, 3 * q, 0);
  const to = `${y}-${String(3 * q).padStart(2, '0')}-${String(toD.getDate()).padStart(2, '0')}`;
  let r;
  try { r = await api(`/operations?kind=income&date_from=${from}&date_to=${to}&limit=200`); } catch (e) { return errorToast(e); }
  const byDay = {};
  r.items.forEach(o => byDay[o.occurred_at] = (byDay[o.occurred_at] || 0) + Number(o.amount_base));
  const days = Object.keys(byDay).sort();
  const total = days.reduce((a, d) => a + byDay[d], 0);
  const prevQ = q === 1 ? `${y - 1}-4` : `${y}-${q - 1}`, nextQ = q === 4 ? `${y + 1}-1` : `${y}-${q + 1}`;
  box.innerHTML = `<div class="card"><div class="card-title"><button class="chip" data-q="${prevQ}" aria-label="prev"><svg class="i" style="width:14px;height:14px;transform:rotate(180deg)"><use href="#i-chev"/></svg></button><span>${w('quarter')} ${q} · ${y}</span><button class="chip" data-q="${nextQ}" aria-label="next"><svg class="i" style="width:14px;height:14px"><use href="#i-chev"/></svg></button></div>
    <div class="scroll-x"><table class="table"><thead><tr><th>№</th><th>${F.t('date')}</th><th class="r">${F.t('income')}</th></tr></thead><tbody>
    ${days.map((d, i) => `<tr><td>${i + 1}</td><td>${fmtDate(d, {day:'2-digit', month:'2-digit', year:'numeric'})}</td><td class="r">${money(byDay[d])}</td></tr>`).join('')}
    <tr><td></td><td><b>${F.t('total')}</b></td><td class="r"><b>${money(total)}</b></td></tr></tbody></table></div></div><p class="hint">${w('bookHint')}</p>`;
  $$('[data-q]', box).forEach(b => b.onclick = () => { S.bookQ = b.dataset.q; renderBook(box); });
}
})();
