/* finplan Business Mini App. Vanilla JS; every check that matters happens on the server. */
(function(){
'use strict';
const tg = window.Telegram && Telegram.WebApp;
const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = (name, cls='i') => `<svg class="${cls}"><use href="#i-${name}"/></svg>`;
const store = {get(k){try{return localStorage.getItem(k)}catch{return null}}, set(k,v){try{localStorage.setItem(k,v)}catch{}}};

/* ------------------------------------------------------------------ i18n */
const I18N = {
uk:{tabHome:'Головна',tabOps:'Операції',tabReports:'Звіти',tabDocs:'Документи',tabMore:'Ще',
 today:'Сьогодні',week:'Тиждень',month:'Місяць',quarter:'Квартал',year:'Рік',
 revenue:'Виручка',expenses:'Витрати',profit:'Прибуток',margin:'Маржа',vsPrev:'до минулого',
 addOp:'Операція',income:'Дохід',expense:'Витрата',transfer:'Переказ',amount:'Сума',category:'Категорія',
 account:'Рахунок',toAccount:'На рахунок',client:'Клієнт / постачальник',project:'Проєкт',note:'Коментар',date:'Дата',
 save:'Зберегти',delete:'Видалити',cancel:'Скасувати',none:'—',all:'Усі',search:'Пошук за коментарем або клієнтом',
 noOps:'Операцій поки немає. Додайте першу кнопкою нижче або напишіть боту «4500 продаж».',
 saved:'Збережено',deleted:'Видалено',taxes:'Податки',taxNext:'Найближчий платіж',limit:'Ліміт доходу',
 single_tax:'Єдиний податок',esv:'ЄСВ',military_levy:'Військовий збір',until:'до',accruing:'квартал ще триває',
 attention:'Потребує уваги',accounts:'Рахунки й каси',balance:'Разом',askAi:'Запитати finplan…',
 business:'Бізнес',name:'Назва',kind:'Тип',fop:'ФОП',company:'Компанія (ТОВ)',freelance:'Фрилансер',
 group:'Група єдиного податку',groupN:'{n} група',notFop:'Не ФОП',rate:'Ставка, %',vat:'Платник ПДВ',paysEsv:'Сплачую ЄСВ',
 currency:'Валюта',categories:'Категорії',projects:'Проєкти',counterparties:'Контрагенти',recurring:'Регулярні операції',
 language:'Мова',theme:'Тема',themeSystem:'Авто',themeLight:'Світла',themeDark:'Темна',
 notifications:'Автоповідомлення',dailyDigest:'Підсумок дня о 21:00',weeklyDigest:'Тижневий звіт у понеділок',monthlyReport:'Звіт 1-го числа',
 add:'Додати',cogs:'Собівартість',incomeCats:'Доходи',expenseCats:'Витрати',opening:'Початковий залишок',
 dayOfMonth:'День місяця',next:'Наступна',onboardTitle:'Налаштуймо бізнес',onboardText:'Облік, звіти й податки за 10 секунд на день.',
 create:'Створити',taxTable:'Податки по кварталах',paid:'Сплачено',due:'До сплати',markPaid:'Позначити сплаченим',
 period:'Період',quarterShort:'Кв.',total:'Разом',incomeTotal:'Дохід',declaration:'Декларація до',
 soon:'Скоро',filters:'Фільтри',member:'Працівник',kindAll:'Усі типи',from:'З',to:'По',
 comingStage:'Цей розділ з’явиться в наступному оновленні.',
 err:'Не вийшло. Спробуйте ще раз.',offline:'Відкрийте finplan Business з бота в Telegram.',
 phone:'Телефон',taxId:'ЄДРПОУ / ІПН',clientK:'Клієнт',supplierK:'Постачальник',bothK:'Обидва',
 role_owner:'Власник',role_admin:'Адміністратор',role_staff:'Працівник',role_accountant:'Бухгалтер',
 sales:'Продажів',avgCheck:'Середній чек',rangeLabel:'{a} – {b}',limitLeft:'залишилось {x}',
 forecast:'Прогноз',personal:'Особисте',businessSw:'Бізнес',switchBiz:'Перемкнути бізнес',newBiz:'+ Новий бізнес'},
ru:{tabHome:'Главная',tabOps:'Операции',tabReports:'Отчёты',tabDocs:'Документы',tabMore:'Ещё',
 today:'Сегодня',week:'Неделя',month:'Месяц',quarter:'Квартал',year:'Год',
 revenue:'Выручка',expenses:'Расходы',profit:'Прибыль',margin:'Маржа',vsPrev:'к прошлому',
 addOp:'Операция',income:'Доход',expense:'Расход',transfer:'Перевод',amount:'Сумма',category:'Категория',
 account:'Счёт',toAccount:'На счёт',client:'Клиент / поставщик',project:'Проект',note:'Комментарий',date:'Дата',
 save:'Сохранить',delete:'Удалить',cancel:'Отмена',none:'—',all:'Все',search:'Поиск по комментарию или клиенту',
 noOps:'Операций пока нет. Добавьте первую кнопкой ниже или напишите боту «4500 продажа».',
 saved:'Сохранено',deleted:'Удалено',taxes:'Налоги',taxNext:'Ближайший платёж',limit:'Лимит дохода',
 single_tax:'Единый налог',esv:'ЕСВ',military_levy:'Военный сбор',until:'до',accruing:'квартал ещё идёт',
 attention:'Нужно внимание',accounts:'Счета и кассы',balance:'Всего',askAi:'Спросить finplan…',
 business:'Бизнес',name:'Название',kind:'Тип',fop:'ФОП',company:'Компания (ТОВ)',freelance:'Фрилансер',
 group:'Группа единого налога',groupN:'{n} группа',notFop:'Не ФОП',rate:'Ставка, %',vat:'Плательщик НДС',paysEsv:'Плачу ЕСВ',
 currency:'Валюта',categories:'Категории',projects:'Проекты',counterparties:'Контрагенты',recurring:'Регулярные операции',
 language:'Язык',theme:'Тема',themeSystem:'Авто',themeLight:'Светлая',themeDark:'Тёмная',
 notifications:'Автосообщения',dailyDigest:'Итог дня в 21:00',weeklyDigest:'Недельный отчёт в понедельник',monthlyReport:'Отчёт 1-го числа',
 add:'Добавить',cogs:'Себестоимость',incomeCats:'Доходы',expenseCats:'Расходы',opening:'Начальный остаток',
 dayOfMonth:'День месяца',next:'Следующая',onboardTitle:'Настроим бизнес',onboardText:'Учёт, отчёты и налоги за 10 секунд в день.',
 create:'Создать',taxTable:'Налоги по кварталам',paid:'Оплачено',due:'К оплате',markPaid:'Отметить оплаченным',
 period:'Период',quarterShort:'Кв.',total:'Итого',incomeTotal:'Доход',declaration:'Декларация до',
 soon:'Скоро',filters:'Фильтры',member:'Сотрудник',kindAll:'Все типы',from:'С',to:'По',
 comingStage:'Этот раздел появится в следующем обновлении.',
 err:'Не получилось. Попробуйте ещё раз.',offline:'Откройте finplan Business из бота в Telegram.',
 phone:'Телефон',taxId:'ЕГРПОУ / ИНН',clientK:'Клиент',supplierK:'Поставщик',bothK:'Оба',
 role_owner:'Владелец',role_admin:'Администратор',role_staff:'Сотрудник',role_accountant:'Бухгалтер',
 sales:'Продаж',avgCheck:'Средний чек',rangeLabel:'{a} – {b}',limitLeft:'осталось {x}',
 forecast:'Прогноз',personal:'Личное',businessSw:'Бизнес',switchBiz:'Переключить бизнес',newBiz:'+ Новый бизнес'},
en:{tabHome:'Home',tabOps:'Operations',tabReports:'Reports',tabDocs:'Documents',tabMore:'More',
 today:'Today',week:'Week',month:'Month',quarter:'Quarter',year:'Year',
 revenue:'Revenue',expenses:'Expenses',profit:'Profit',margin:'Margin',vsPrev:'vs previous',
 addOp:'Operation',income:'Income',expense:'Expense',transfer:'Transfer',amount:'Amount',category:'Category',
 account:'Account',toAccount:'To account',client:'Client / supplier',project:'Project',note:'Note',date:'Date',
 save:'Save',delete:'Delete',cancel:'Cancel',none:'—',all:'All',search:'Search notes or clients',
 noOps:'No operations yet. Add one below or text the bot “4500 sale”.',
 saved:'Saved',deleted:'Deleted',taxes:'Taxes',taxNext:'Next payment',limit:'Income limit',
 single_tax:'Single tax',esv:'Social contribution (ESV)',military_levy:'Military levy',until:'by',accruing:'quarter in progress',
 attention:'Needs attention',accounts:'Accounts & cash',balance:'Total',askAi:'Ask finplan…',
 business:'Business',name:'Name',kind:'Type',fop:'FOP',company:'Company',freelance:'Freelancer',
 group:'Single tax group',groupN:'Group {n}',notFop:'Not a FOP',rate:'Rate, %',vat:'VAT payer',paysEsv:'I pay ESV',
 currency:'Currency',categories:'Categories',projects:'Projects',counterparties:'Clients & suppliers',recurring:'Recurring',
 language:'Language',theme:'Theme',themeSystem:'Auto',themeLight:'Light',themeDark:'Dark',
 notifications:'Automatic messages',dailyDigest:'Day summary at 21:00',weeklyDigest:'Weekly report on Monday',monthlyReport:'Report on the 1st',
 add:'Add',cogs:'Cost of goods',incomeCats:'Income',expenseCats:'Expenses',opening:'Opening balance',
 dayOfMonth:'Day of month',next:'Next',onboardTitle:'Set up your business',onboardText:'Books, reports and taxes in 10 seconds a day.',
 create:'Create',taxTable:'Taxes by quarter',paid:'Paid',due:'Due',markPaid:'Mark as paid',
 period:'Period',quarterShort:'Q',total:'Total',incomeTotal:'Income',declaration:'Return by',
 soon:'Soon',filters:'Filters',member:'Member',kindAll:'All types',from:'From',to:'To',
 comingStage:'This section arrives in the next update.',
 err:'Something went wrong. Try again.',offline:'Open finplan Business from its Telegram bot.',
 phone:'Phone',taxId:'Tax id',clientK:'Client',supplierK:'Supplier',bothK:'Both',
 role_owner:'Owner',role_admin:'Admin',role_staff:'Staff',role_accountant:'Accountant',
 sales:'Sales',avgCheck:'Average check',rangeLabel:'{a} – {b}',limitLeft:'{x} left',
 forecast:'Forecast',personal:'Personal',businessSw:'Business',switchBiz:'Switch business',newBiz:'+ New business'}
};
let LANG = 'uk';
const t = (k, vars) => { let s = (I18N[LANG] && I18N[LANG][k]) || I18N.ru[k] || k; if (vars) for (const [a,b] of Object.entries(vars)) s = s.replace('{'+a+'}', b); return s; };
const LOCALE = () => ({uk:'uk-UA', ru:'ru-RU', en:'en-GB'}[LANG]);

/* ------------------------------------------------------------------ state & api */
const S = {me:null, meta:null, tab:'home', period:'month', dash:null, opsFilter:{kind:''}, ops:[], opsQuery:''};
window.FB = {S, t, esc, icon, $, $$};

function headers(){
  const h = {'Content-Type':'application/json'};
  if (tg && tg.initData) h['X-Telegram-Init-Data'] = tg.initData;
  else { const dev = new URLSearchParams(location.search).get('dev') || store.get('fb-dev'); if (dev){ h['X-Dev-Telegram-User'] = dev; store.set('fb-dev', dev); } }
  const biz = store.get('fb-business'); if (biz) h['X-Business-Id'] = biz;
  return h;
}
class ApiError extends Error { constructor(status, detail){ super(typeof detail === 'string' ? detail : (detail && detail.message) || 'Error'); this.status = status; this.detail = detail; } }
async function api(path, opts={}){
  const res = await fetch('/api' + path, {...opts, headers:{...headers(), ...(opts.headers||{})}});
  let data = null; try { data = await res.json(); } catch {}
  if (!res.ok) {
    const err = new ApiError(res.status, data && data.detail);
    if (res.status === 402 && window.FB.onPlanRequired) window.FB.onPlanRequired(err.detail);
    throw err;
  }
  return data;
}
const post = (p, body) => api(p, {method:'POST', body: JSON.stringify(body || {})});
const patch = (p, body) => api(p, {method:'PATCH', body: JSON.stringify(body || {})});
const del = p => api(p, {method:'DELETE'});
Object.assign(window.FB, {api, post, patch, del, ApiError});

/* ------------------------------------------------------------------ formatting */
const SIGNS = {UAH:'₴', USD:'$', EUR:'€', PLN:'zł', GBP:'£'};
function money(v, cur, sign){
  cur = cur || (S.me && S.me.business && S.me.business.currency) || 'UAH';
  const n = Number(v || 0);
  const abs = Math.abs(n).toLocaleString(LOCALE(), {minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2});
  const pre = sign ? (n > 0 ? '+' : n < 0 ? '−' : '') : (n < 0 ? '−' : '');
  return `${pre}${abs} ${SIGNS[cur] || cur}`;
}
const fmtDate = (d, opts) => new Date(d + 'T12:00:00').toLocaleDateString(LOCALE(), opts || {day:'numeric', month:'short'});
const todayISO = () => (S.me && S.me.today) || new Date().toISOString().slice(0,10);
function delta(pct, goodWhenUp=true){
  if (pct === null || pct === undefined) return '<span class="delta">&nbsp;</span>';
  const up = pct > 0, good = (up === goodWhenUp) || pct === 0;
  return `<span class="delta ${pct === 0 ? '' : good ? 'good' : 'bad'}">${pct === 0 ? '' : icon(up ? 'up' : 'down')}${up ? '+' : ''}${pct}% ${t('vsPrev')}</span>`;
}
Object.assign(window.FB, {money, fmtDate, delta, todayISO});

/* ------------------------------------------------------------------ ui helpers */
let toastTimer;
function toast(msg){ const el = $('#toast'); el.textContent = msg; el.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 2600); }
function openSheet(html, onMount){
  const sheet = $('#sheet'), back = $('#backdrop');
  $('#sheet-body').innerHTML = html; sheet.hidden = back.hidden = false;
  requestAnimationFrame(() => { sheet.classList.add('show'); back.classList.add('show'); });
  if (onMount) onMount($('#sheet-body'));
  tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred && tg.HapticFeedback.impactOccurred('light');
}
function closeSheet(){
  const sheet = $('#sheet'), back = $('#backdrop');
  sheet.classList.remove('show'); back.classList.remove('show');
  setTimeout(() => { sheet.hidden = back.hidden = true; $('#sheet-body').innerHTML = ''; }, 220);
}
$('#backdrop').addEventListener('click', closeSheet);
function errorToast(e){ console.error(e); if (e && e.status === 402) return; toast((e && e.message && e.message !== 'Error') ? e.message : t('err')); }
const can = p => !!(S.me && S.me.permissions && S.me.permissions.includes(p));
const opts = (rows, sel, empty) => (empty !== undefined ? `<option value="">${esc(empty)}</option>` : '') + rows.map(r => `<option value="${r.id}"${String(r.id) === String(sel ?? '') ? ' selected' : ''}>${esc(r.name)}</option>`).join('');
Object.assign(window.FB, {toast, openSheet, closeSheet, errorToast, can, opts});

/* ------------------------------------------------------------------ theme */
function applyTheme(){
  const pref = new URLSearchParams(location.search).get('theme') || (S.me && S.me.user.theme !== 'system' && S.me.user.theme) || store.get('fb-theme') || 'system';
  const dark = pref === 'dark' || (pref === 'system' && (tg && tg.initData ? tg.colorScheme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches));
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  $('#theme-btn').innerHTML = icon(dark ? 'sun' : 'moon');
  const bg = dark ? '#0F1512' : '#F4F5F1';
  try { tg && tg.setHeaderColor && tg.setHeaderColor(bg); } catch {}
  try { tg && tg.setBackgroundColor && tg.setBackgroundColor(bg); } catch {}
  // On iPhone Telegram draws its own bar under the Mini App; paint it with the page colour.
  try { tg && tg.setBottomBarColor && tg.setBottomBarColor(dark ? '#222C26' : '#E8ECE6'); } catch {}
}
$('#theme-btn').addEventListener('click', async () => {
  const dark = document.documentElement.dataset.theme === 'dark';
  const theme = dark ? 'light' : 'dark';
  store.set('fb-theme', theme);
  if (S.me) { S.me.user.theme = theme; patch('/me', {theme}).catch(() => {}); }
  applyTheme(); if (S.tab === 'home' && S.dash) renderHome();
});
tg && tg.onEvent && tg.onEvent('themeChanged', applyTheme);

/* ------------------------------------------------------------------ navigation */
const TABS = {};
window.FB.TABS = TABS;
function go(tab){
  S.tab = tab;
  $$('#nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  window.scrollTo(0, 0);
  (TABS[tab] || TABS.home)();
}
window.FB.go = go;
$$('#nav button').forEach(b => b.addEventListener('click', () => go(b.dataset.tab)));
function translateStatic(){ $$('[data-t]').forEach(el => el.textContent = t(el.dataset.t)); document.documentElement.lang = LANG; }

function renderTop(){
  const me = S.me, b = me && me.business;
  $('#biz-name').textContent = b ? b.name : 'finplan Business';
  $('#biz-sub').textContent = b ? `${b.kind === 'company' ? t('company') : b.fop_group ? t('fop') + ' · ' + t('groupN', {n: b.fop_group}) : t(b.kind)} · ${t('role_' + b.role)}` : '';
  const plan = me && me.plan;
  $('#plan-badge').innerHTML = plan ? (plan.plan === 'free' ? '<span class="badge-free">Free</span>' : `<span class="badge-pro">${plan.plan === 'team' ? 'TEAM' : 'PRO'}</span>`) : '';
  $('#nav').hidden = !b;
}
$('#brand').addEventListener('click', () => { if (S.me && S.me.businesses.length) switchSheet(); });
function switchSheet(){
  const me = S.me;
  const rows = me.businesses.map(b => `<div class="row tap" data-biz="${b.id}"><span class="ic">${icon('folder')}</span><span class="grow"><b>${esc(b.name)}</b><small>${t('role_' + b.role)}</small></span>${b.id === me.business.id ? icon('check', 'i pos') : ''}</div>`).join('');
  const personal = me.personal_app_url ? `<a class="btn ghost" style="margin-top:12px;text-decoration:none" href="${esc(me.personal_app_url)}">${icon('person')} ${t('personal')}</a>` : '';
  openSheet(`<h2>${t('switchBiz')}</h2><div class="card flat">${rows}</div>${personal}<button class="btn ghost" style="margin-top:10px" id="new-biz">${t('newBiz')}</button>`, el => {
    $$('[data-biz]', el).forEach(r => r.addEventListener('click', async () => { store.set('fb-business', r.dataset.biz); closeSheet(); await boot(); }));
    $('#new-biz', el).addEventListener('click', () => { closeSheet(); renderOnboarding(true); });
    if (me.personal_app_url && tg && tg.openTelegramLink && me.personal_app_url.startsWith('https://t.me/')) {
      el.querySelector('a.btn').addEventListener('click', e => { e.preventDefault(); tg.openTelegramLink(me.personal_app_url); });
    }
  });
}

/* ------------------------------------------------------------------ onboarding */
function renderOnboarding(again){
  $('#nav').hidden = !again;
  const v = $('#view');
  v.innerHTML = `<section class="onboard">
    <svg class="logo"><use href="#logo"/></svg>
    <h1>${t('onboardTitle')}</h1><p>${t('onboardText')}</p>
    <form class="card" id="ob">
      <label class="f">${t('name')}<input class="in" name="name" required maxlength="120" placeholder="ФОП Іваненко"></label>
      <label class="f">${t('kind')}<select class="in" name="kind"><option value="fop">${t('fop')}</option><option value="freelance">${t('freelance')}</option><option value="company">${t('company')}</option></select></label>
      <label class="f" id="ob-group">${t('group')}<select class="in" name="fop_group"><option value="1">${t('groupN',{n:1})}</option><option value="2">${t('groupN',{n:2})}</option><option value="3" selected>${t('groupN',{n:3})}</option><option value="">${t('notFop')}</option></select></label>
      <div class="switch" id="ob-vat"><span>${t('vat')}</span><input type="checkbox" name="is_vat_payer"></div>
      <button class="btn big" type="submit">${t('create')}</button>
    </form></section>`;
  const f = $('#ob');
  const sync = () => { const company = f.kind.value === 'company'; $('#ob-group').hidden = company; $('#ob-vat').hidden = company || f.fop_group.value !== '3'; };
  f.kind.onchange = f.fop_group.onchange = sync; sync();
  f.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      const b = await post('/business', {name: f.name.value.trim(), kind: f.kind.value, fop_group: f.kind.value === 'company' || !f.fop_group.value ? null : Number(f.fop_group.value), is_vat_payer: f.is_vat_payer.checked});
      store.set('fb-business', b.id); await boot();
    } catch (err) { errorToast(err); }
  });
}

/* ------------------------------------------------------------------ home */
const PERIODS = ['today', 'week', 'month', 'quarter', 'year'];
async function loadHome(){
  const v = $('#view');
  if (!S.dash) v.innerHTML = `<div class="chips">${PERIODS.map(p => `<button class="chip${p === S.period ? ' on' : ''}">${t(p)}</button>`).join('')}</div><div class="card" style="height:220px"></div>`;
  try { S.dash = await api('/dashboard?period=' + S.period); S.dashLocked = null; }
  catch (e) { if (e.status === 402) { S.dashLocked = e.detail; S.dash = null; } else return errorToast(e); }
  renderHome();
}
TABS.home = loadHome;

function chartSVG(series, kind){
  const W = 320, H = 150, pad = 18, n = series.length || 1;
  const max = Math.max(1, ...series.map(r => Math.max(Number(r.income), Number(r.expense))));
  const slot = (W - 4) / n, bw = Math.max(2, Math.min(12, slot * 0.36));
  let bars = '', labels = '';
  series.forEach((r, i) => {
    const x = 2 + i * slot + slot / 2;
    const hi = (Number(r.income) / max) * (H - pad - 6), he = (Number(r.expense) / max) * (H - pad - 6);
    bars += `<rect x="${(x - bw - 1).toFixed(1)}" y="${(H - pad - hi).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(hi, .5).toFixed(1)}" rx="${Math.min(3, bw/2)}" fill="var(--primary)"/>`;
    bars += `<rect x="${(x + 1).toFixed(1)}" y="${(H - pad - he).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(he, .5).toFixed(1)}" rx="${Math.min(3, bw/2)}" fill="var(--expense)" opacity=".85"/>`;
    const every = n <= 8 ? 1 : n <= 16 ? 3 : n <= 31 ? 7 : 2;
    if (i % every === 0 || i === n - 1 && n <= 8) {
      const label = kind === 'month' ? new Date(r.month + '-15').toLocaleDateString(LOCALE(), {month:'short'}) : (n <= 7 ? new Date(r.date + 'T12:00').toLocaleDateString(LOCALE(), {weekday:'short'}) : String(Number(r.date.slice(8))));
      labels += `<text x="${x.toFixed(1)}" y="${H - 3}" text-anchor="middle" font-size="9.5" fill="var(--muted)" font-weight="600">${esc(label)}</text>`;
    }
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${H - pad}" y2="${H - pad}" stroke="var(--line)"/>${bars}${labels}</svg>`;
}
window.FB.chartSVG = chartSVG;

function taxCard(tax){
  if (!tax || !tax.applicable) return '';
  const next = tax.next && tax.next[0];
  const lim = tax.limit;
  const nextLine = next ? `<div style="font-size:15px;font-weight:700">${t(next.what)} ${next.period.includes('Q') ? t('quarterShort') + next.period.slice(-1) : ''}: ${money(next.amount, 'UAH')}, ${t('until')} ${fmtDate(next.due_date, {day:'numeric', month:'long'})}</div>${next.accruing ? `<div class="small muted">${t('accruing')}</div>` : ''}` : '';
  const more = (tax.next || []).slice(1, 3).map(p => `<div class="small muted" style="margin-top:4px">${t(p.what)}: ${money(p.amount, 'UAH')} ${t('until')} ${fmtDate(p.due_date)}</div>`).join('');
  const limit = lim ? `<div style="margin-top:14px" class="small"><div style="display:flex;justify-content:space-between;gap:8px"><b>${t('limit')}</b><span class="muted">${lim.percent}% · ${t('limitLeft', {x: money(lim.left, 'UAH')})}</span></div>
    <div class="progress ${lim.percent >= 100 ? 'over' : lim.percent >= 70 ? 'warn' : ''}"><i style="width:${Math.min(100, lim.percent)}%"></i></div></div>` : '';
  return `<div class="card tap-card" id="tax-card"><div class="card-title"><span>${icon('tax')} ${t('taxes')}</span>${icon('chev','i chev')}</div>${nextLine}${more}${limit}</div>`;
}

function attentionCard(items){
  if (!items || !items.length) return '';
  const rows = items.map(a => {
    if (a.kind === 'cash_gap') return `<div class="row"><span class="ic warn">${icon('alert')}</span><span class="grow"><b>${fmtDate(a.date, {day:'numeric', month:'long'})}: ${esc(a.note || t('expense'))} ${money(a.amount)}</b><small>${t('accounts')}: ${money(a.balance)}</small></span></div>`;
    const days = a.days ? ` · ${a.days} дн.` : '';
    const title = a.kind === 'invoice_overdue' ? `№${a.number} ${esc(a.counterparty || '')}` : esc(a.counterparty || '');
    return `<div class="row tap" data-goto="docs"><span class="ic warn">${icon(a.kind === 'invoice_overdue' ? 'doc' : 'person')}</span><span class="grow"><b>${title}</b><small>${money(a.amount)}${days}</small></span>${icon('chev','i chev')}</div>`;
  }).join('');
  return `<div class="card"><div class="card-title"><span>${t('attention')}</span></div>${rows}</div>`;
}

function renderHome(){
  const v = $('#view'), d = S.dash;
  const chips = `<div class="chips">${PERIODS.map(p => `<button class="chip${p === S.period ? ' on' : ''}" data-period="${p}">${t(p)}</button>`).join('')}</div>`;
  if (S.dashLocked) {
    v.innerHTML = chips + (window.FB.lockedCard ? window.FB.lockedCard(S.dashLocked) : `<div class="card empty">${t('soon')}</div>`) + addButton();
  } else if (d) {
    const s = d.summary, ch = d.change || {};
    const range = d.start === d.end ? fmtDate(d.start, {day:'numeric', month:'long'}) : t('rangeLabel', {a: fmtDate(d.start), b: fmtDate(d.end)});
    const kpis = `<div class="kpis">
      <div class="card kpi"><span>${t('revenue')}</span><strong>${money(s.revenue)}</strong>${delta(ch.revenue, true)}</div>
      <div class="card kpi"><span>${t('expenses')}</span><strong>${money(s.expenses)}</strong>${delta(ch.expenses, false)}</div>
      <div class="card kpi"><span>${t('profit')}</span><strong class="${Number(s.profit) < 0 ? 'neg' : ''}">${money(s.profit)}</strong>${delta(ch.profit, true)}</div>
      <div class="card kpi"><span>${t('margin')}</span><strong>${s.margin === null ? '—' : s.margin + '%'}</strong><span class="delta">${s.sales_count ? `${t('sales')}: ${s.sales_count}` : '&nbsp;'}</span></div></div>`;
    const chart = `<div class="card" style="margin-top:12px"><div class="card-title"><span>${range}</span>${d.forecast ? `<span>${t('forecast')}: ${money(d.forecast.revenue_month_end)}</span>` : ''}</div>${chartSVG(d.series, d.series_kind)}<div class="legend"><span><i style="background:var(--primary)"></i>${t('revenue')}</span><span><i style="background:var(--expense)"></i>${t('expenses')}</span></div></div>`;
    const accounts = d.accounts && d.accounts.length ? `<div class="section-head"><h2>${t('accounts')}</h2><span class="muted small">${t('balance')}: <b style="color:var(--ink)">${money(d.balance)}</b></span></div><div class="accounts">${d.accounts.map(a => `<div class="card acc"><span>${esc(a.name)}</span><strong class="${Number(a.balance) < 0 ? 'neg' : ''}">${money(a.balance)}</strong></div>`).join('')}</div>` : '';
    const ask = window.FB.askRow ? window.FB.askRow() : '';
    v.innerHTML = chips + kpis + chart + `<div style="margin-top:12px">${taxCard(d.tax)}</div>` + `<div style="margin-top:12px">${attentionCard(d.attention)}</div>` + ask + addButton() + accounts;
  }
  $$('[data-period]', v).forEach(b => b.addEventListener('click', () => { S.period = b.dataset.period; loadHome(); }));
  const tc = $('#tax-card'); if (tc) tc.addEventListener('click', () => { S.docsTab = 'taxes'; go('docs'); });
  $$('[data-goto]', v).forEach(r => r.addEventListener('click', () => go(r.dataset.goto)));
  const add = $('#add-op'); if (add) add.addEventListener('click', () => opForm());
  if (window.FB.afterHome) window.FB.afterHome(v);
}
function addButton(){ return can('add_operation') ? `<button class="btn big" id="add-op">${icon('plus')} ${t('addOp')}</button>` : ''; }

/* ------------------------------------------------------------------ operation form */
function opForm(op){
  const m = S.meta, editing = !!op;
  op = op || {kind:'income', occurred_at: todayISO()};
  const html = `<h2>${editing ? t('save') : t('addOp')}<button class="icon-btn" id="x">${icon('x')}</button></h2>
  <form id="opf">
    <div class="seg" id="kind">${['income','expense','transfer'].map(k => `<button type="button" data-k="${k}" class="${op.kind === k ? 'on' : ''}">${t(k)}</button>`).join('')}</div>
    <input class="in amount" name="amount" inputmode="decimal" placeholder="0" value="${op.amount ? Number(op.amount) : ''}" required>
    <div class="grid2" style="margin-top:12px">
      <label class="f" data-for="income expense">${t('category')}<select class="in" name="category_id"></select></label>
      <label class="f">${t('date')}<input class="in" type="date" name="occurred_at" value="${op.occurred_at}"></label>
    </div>
    <div class="grid2">
      <label class="f">${t('account')}<select class="in" name="account_id">${opts(m.accounts, op.account_id, t('none'))}</select></label>
      <label class="f" data-for="transfer">${t('toAccount')}<select class="in" name="to_account_id">${opts(m.accounts, op.to_account_id, t('none'))}</select></label>
      <label class="f" data-for="income expense">${t('currency')}<select class="in" name="currency">${m.currencies.map(c => `<option${(op.currency || S.me.business.currency) === c ? ' selected' : ''}>${c}</option>`).join('')}</select></label>
    </div>
    <label class="f" data-for="income expense">${t('client')}<select class="in" name="counterparty_id">${opts(m.counterparties, op.counterparty_id, t('none'))}</select></label>
    ${m.projects.length ? `<label class="f" data-for="income expense">${t('project')}<select class="in" name="project_id">${opts(m.projects.filter(p => !p.archived || p.id === op.project_id), op.project_id, t('none'))}</select></label>` : ''}
    ${window.FB.productField ? window.FB.productField(op) : ''}
    <label class="f">${t('note')}<input class="in" name="note" maxlength="500" value="${esc(op.note || '')}"></label>
    <button class="btn" type="submit">${t('save')}</button>
    ${editing ? `<button class="btn danger" type="button" id="del" style="margin-top:8px">${icon('trash')} ${t('delete')}</button>` : ''}
  </form>`;
  openSheet(html, el => {
    const f = $('#opf', el); let kind = op.kind;
    const fillCats = () => { f.category_id.innerHTML = opts(m.categories.filter(c => c.kind === kind), op.kind === kind ? op.category_id : null, t('none')); };
    const sync = () => {
      $$('[data-k]', el).forEach(b => b.classList.toggle('on', b.dataset.k === kind));
      $$('[data-for]', el).forEach(x => x.hidden = !x.dataset.for.split(' ').includes(kind));
      fillCats();
    };
    $$('[data-k]', el).forEach(b => b.addEventListener('click', () => { kind = b.dataset.k; sync(); }));
    sync();
    $('#x', el).addEventListener('click', closeSheet);
    if (!editing) setTimeout(() => f.amount.focus(), 250);
    f.addEventListener('submit', async e => {
      e.preventDefault();
      const num = v => v ? Number(v) : null;
      const body = {kind, amount: String(f.amount.value).replace(/\s/g, '').replace(',', '.'), occurred_at: f.occurred_at.value || null,
        account_id: num(f.account_id.value), note: f.note.value.trim() || null};
      if (kind === 'transfer') body.to_account_id = num(f.to_account_id.value);
      else { body.category_id = num(f.category_id.value); body.counterparty_id = num(f.counterparty_id.value); body.currency = f.currency.value;
        if (f.project_id) body.project_id = num(f.project_id.value);
        if (f.product_id && f.product_id.value) { body.product_id = num(f.product_id.value); body.quantity = f.quantity.value || 1; } }
      try { editing ? await patch('/operations/' + op.id, body) : await post('/operations', body); closeSheet(); toast(t('saved')); refresh(); }
      catch (err) { errorToast(err); }
    });
    const d = $('#del', el);
    if (d) d.addEventListener('click', async () => { try { await del('/operations/' + op.id); closeSheet(); toast(t('deleted')); refresh(); } catch (err) { errorToast(err); } });
  });
}
window.FB.opForm = opForm;
async function refresh(){ try { S.meta = await api('/meta'); } catch {} S.dash = null; go(S.tab); }
window.FB.refresh = refresh;

/* ------------------------------------------------------------------ operations */
const byId = (rows, id) => (rows || []).find(r => r.id === id);
function opRow(o){
  const m = S.meta, cat = byId(m.categories, o.category_id), cp = byId(m.counterparties, o.counterparty_id);
  const acc = byId(m.accounts, o.account_id), to = byId(m.accounts, o.to_account_id);
  const title = o.kind === 'transfer' ? `${acc ? acc.name : '?'} → ${to ? to.name : '?'}` : (cat ? cat.name : t(o.kind));
  const sub = [cp && cp.name, o.note, o.source === 'bank' ? 'monobank' : null].filter(Boolean).join(' · ');
  const cls = o.kind === 'income' ? 'in' : o.kind === 'expense' ? 'out' : 'tr';
  const amount = o.kind === 'transfer' ? money(o.amount, o.currency) : money(o.kind === 'income' ? o.amount : -o.amount, o.currency, true);
  return `<div class="row tap" data-op="${o.id}"><span class="ic ${cls}">${icon(o.kind === 'income' ? 'in' : o.kind === 'expense' ? 'out' : 'swap')}</span><span class="grow"><b>${esc(title)}</b><small>${esc(sub) || '&nbsp;'}</small></span><span class="amt ${o.kind === 'income' ? 'pos' : o.kind === 'expense' ? '' : 'muted'}">${amount}</span></div>`;
}
window.FB.opRow = opRow;
TABS.ops = async function(){
  const v = $('#view'), f = S.opsFilter, m = S.meta;
  const kinds = [['', t('all')], ['income', t('income')], ['expense', t('expense')], ['transfer', t('transfer')]];
  v.innerHTML = `<h1>${t('tabOps')}</h1>
    <div class="card flat" style="display:flex;align-items:center;gap:8px;padding:4px 12px;margin-bottom:10px">${icon('search','i muted')}<input class="in" id="q" style="border:0;background:none;padding:10px 0" placeholder="${t('search')}" value="${esc(S.opsQuery)}"><button class="icon-btn" id="flt" style="border:0">${icon('filter')}</button></div>
    <div class="chips">${kinds.map(([k, l]) => `<button class="chip${(f.kind || '') === k ? ' on' : ''}" data-kind="${k}">${l}</button>`).join('')}</div>
    <div id="filters" class="card flat" ${S.showFilters ? '' : 'hidden'} style="margin-bottom:12px">
      <div class="grid2"><label class="f">${t('category')}<select class="in" data-f="category_id">${opts(m.categories, f.category_id, t('all'))}</select></label>
      <label class="f">${t('client')}<select class="in" data-f="counterparty_id">${opts(m.counterparties, f.counterparty_id, t('all'))}</select></label></div>
      <div class="grid2"><label class="f">${t('project')}<select class="in" data-f="project_id">${opts(m.projects, f.project_id, t('all'))}</select></label>
      <label class="f">${t('member')}<select class="in" data-f="member_id">${opts(m.members, f.member_id, t('all'))}</select></label></div>
      <div class="grid2"><label class="f">${t('from')}<input class="in" type="date" data-f="date_from" value="${f.date_from || ''}"></label><label class="f">${t('to')}<input class="in" type="date" data-f="date_to" value="${f.date_to || ''}"></label></div>
    </div>
    <div id="op-list"><div class="card" style="height:160px"></div></div>${addButton()}`;
  const load = async () => {
    const p = new URLSearchParams(); Object.entries(f).forEach(([k, val]) => val && p.set(k, val)); if (S.opsQuery) p.set('q', S.opsQuery); p.set('limit', '150');
    try { const r = await api('/operations?' + p); S.ops = r.items; renderOps(); } catch (e) { errorToast(e); }
  };
  let timer; $('#q').addEventListener('input', e => { S.opsQuery = e.target.value; clearTimeout(timer); timer = setTimeout(load, 300); });
  $('#flt').addEventListener('click', () => { S.showFilters = !S.showFilters; $('#filters').hidden = !S.showFilters; });
  $$('[data-kind]', v).forEach(b => b.addEventListener('click', () => { f.kind = b.dataset.kind; $$('[data-kind]', v).forEach(x => x.classList.toggle('on', x === b)); load(); }));
  $$('[data-f]', v).forEach(s => s.addEventListener('change', () => { f[s.dataset.f] = s.value; load(); }));
  const add = $('#add-op'); if (add) add.addEventListener('click', () => opForm());
  load();
};
function renderOps(){
  const list = $('#op-list'); if (!list) return;
  if (!S.ops.length) { list.innerHTML = `<div class="card empty">${icon('list')}<div>${t('noOps')}</div></div>`; return; }
  const groups = {};
  S.ops.forEach(o => (groups[o.occurred_at] = groups[o.occurred_at] || []).push(o));
  list.innerHTML = Object.entries(groups).map(([day, rows]) => {
    const net = rows.reduce((a, o) => a + (o.kind === 'income' ? +o.amount_base : o.kind === 'expense' ? -o.amount_base : 0), 0);
    return `<div class="day-head"><span>${fmtDate(day, {weekday:'short', day:'numeric', month:'long'})}</span><span>${money(net, null, true)}</span></div><div class="card">${rows.map(opRow).join('')}</div>`;
  }).join('');
  $$('[data-op]', list).forEach(r => r.addEventListener('click', () => { const o = S.ops.find(x => x.id === Number(r.dataset.op)); if (o) opForm(o); }));
}

/* ------------------------------------------------------------------ documents (taxes) */
TABS.docs = async function(){
  const v = $('#view');
  const subs = window.FB.docTabs || [['taxes', t('taxes')]];
  S.docsTab = S.docsTab || subs[0][0];
  v.innerHTML = `<h1>${t('tabDocs')}</h1><div class="chips">${subs.map(([k, l]) => `<button class="chip${S.docsTab === k ? ' on' : ''}" data-dt="${k}">${l}</button>`).join('')}</div><div id="doc-body"><div class="card" style="height:200px"></div></div>`;
  $$('[data-dt]', v).forEach(b => b.addEventListener('click', () => { S.docsTab = b.dataset.dt; TABS.docs(); }));
  const handler = (window.FB.docHandlers || {})[S.docsTab] || renderTaxes;
  try { await handler($('#doc-body')); } catch (e) { errorToast(e); }
};
async function renderTaxes(box){
  if (!can('read')) { box.innerHTML = `<div class="card empty">${icon('lock')}<div>—</div></div>`; return; }
  const year = S.taxYear || new Date(todayISO()).getFullYear();
  const d = await api('/tax?year=' + year);
  if (!d.applicable) { box.innerHTML = `<div class="card empty">${icon('tax')}<div>${LANG === 'en' ? 'Taxes are calculated for FOP groups 1–3. Set the group in More → Business.' : LANG === 'ru' ? 'Налоги считаются для ФОП 1–3 группы. Укажите группу в Ещё → Бизнес.' : 'Податки рахуються для ФОП 1–3 групи. Вкажіть групу в Ще → Бізнес.'}</div></div>`; return; }
  const rows = d.quarters.map(q => q.future ? `<tr class="muted"><td>${t('quarterShort')}${q.quarter}</td><td class="r">—</td><td class="r">—</td><td class="r">—</td><td></td></tr>` :
    `<tr><td><b>${t('quarterShort')}${q.quarter}</b></td><td class="r">${money(q.income_total, 'UAH')}</td><td class="r">${money(Number(q.single_tax) + Number(q.military_levy), 'UAH')}</td><td class="r">${money(q.esv, 'UAH')}</td>
     <td class="r"><button class="pill ${q.status === 'paid' ? 'ok' : 'warn'}" style="border:0" data-pay="${q.period}" data-paid="${q.status === 'paid' ? 1 : 0}">${q.status === 'paid' ? t('paid') : t('due')}</button></td></tr>`).join('');
  const up = d.upcoming.map(p => `<div class="row"><span class="ic">${icon('tax')}</span><span class="grow"><b>${t(p.what)} · ${p.period}</b><small>${t('until')} ${fmtDate(p.due_date, {day:'numeric', month:'long', year:'numeric'})}${p.accruing ? ' · ' + t('accruing') : ''}${p.declaration_date && !p.accruing ? ' · ' + t('declaration') + ' ' + fmtDate(p.declaration_date) : ''}</small></span><span class="amt">${money(p.amount, 'UAH')}</span></div>`).join('');
  const lim = d.limit;
  box.innerHTML = `${up ? `<div class="card"><div class="card-title"><span>${t('taxNext')}</span><span>${t('groupN', {n: d.group})}${d.group === 3 ? ' · ' + Number(d.rate) + '%' : ''}</span></div>${up}</div>` : ''}
    <div class="card"><div class="card-title"><span>${t('taxTable')}</span><span style="display:flex;gap:6px"><button class="chip" data-y="-1">${year - 1}</button><button class="chip on">${year}</button>${year < new Date(todayISO()).getFullYear() ? `<button class="chip" data-y="1">${year + 1}</button>` : ''}</span></div>
    <div class="scroll-x"><table class="table"><thead><tr><th>${t('period')}</th><th class="r">${t('incomeTotal')}</th><th class="r">${t('single_tax')}</th><th class="r">${t('esv')}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>
    ${lim ? `<div class="card"><div class="card-title"><span>${t('limit')} ${new Date(todayISO()).getFullYear()}</span><span>${lim.percent}%</span></div><div style="font-weight:700">${money(lim.used, 'UAH')} / ${money(lim.limit, 'UAH')}</div><div class="progress ${lim.percent >= 100 ? 'over' : lim.percent >= 70 ? 'warn' : ''}"><i style="width:${Math.min(100, lim.percent)}%"></i></div></div>` : ''}
    <p class="disclaimer">${esc(S.me.disclaimer[LANG] || S.me.disclaimer.uk)}</p>`;
  $$('[data-y]', box).forEach(b => b.addEventListener('click', () => { S.taxYear = year + Number(b.dataset.y); renderTaxes(box); }));
  $$('[data-pay]', box).forEach(b => b.addEventListener('click', async () => {
    if (!can('write')) return;
    try { await post(`/tax/${b.dataset.pay}/paid`, {paid: b.dataset.paid !== '1'}); renderTaxes(box); } catch (e) { errorToast(e); }
  }));
}
window.FB.renderTaxes = renderTaxes;

/* ------------------------------------------------------------------ reports (placeholder until reports.js) */
TABS.reports = function(){ $('#view').innerHTML = `<h1>${t('tabReports')}</h1><div class="card empty">${icon('chart')}<div>${t('comingStage')}</div></div>`; };

/* ------------------------------------------------------------------ more */
function listCard(title, rows, addId){
  return `<div class="section-head"><h2>${title}</h2>${addId && can('manage') ? `<button class="link" id="${addId}">${t('add')}</button>` : ''}</div><div class="card">${rows || `<div class="empty" style="padding:10px">—</div>`}</div>`;
}
window.FB.listCard = listCard;
TABS.more = async function(){
  const v = $('#view'), b = S.me.business, m = S.meta;
  const manage = can('manage');
  const sections = [];
  if (window.FB.planCard) sections.push(window.FB.planCard());
  sections.push(`<div class="section-head"><h2>${t('business')}</h2></div><form class="card" id="bizf">
    <label class="f">${t('name')}<input class="in" name="name" value="${esc(b.name)}" ${manage ? '' : 'disabled'}></label>
    <div class="grid2"><label class="f">${t('kind')}<select class="in" name="kind" ${manage ? '' : 'disabled'}>${['fop','freelance','company'].map(k => `<option value="${k}"${b.kind === k ? ' selected' : ''}>${t(k)}</option>`).join('')}</select></label>
    <label class="f">${t('group')}<select class="in" name="fop_group" ${manage ? '' : 'disabled'}><option value="0">${t('notFop')}</option>${[1,2,3].map(n => `<option value="${n}"${b.fop_group === n ? ' selected' : ''}>${t('groupN', {n})}</option>`).join('')}</select></label></div>
    <div class="grid2"><label class="f">${t('rate')}<input class="in" name="tax_rate" inputmode="decimal" value="${Number(b.tax_rate)}" ${manage ? '' : 'disabled'}></label>
    <label class="f">${t('currency')}<select class="in" name="currency" ${manage ? '' : 'disabled'}>${m.currencies.map(c => `<option${b.currency === c ? ' selected' : ''}>${c}</option>`).join('')}</select></label></div>
    <div class="switch"><span>${t('vat')}</span><input type="checkbox" name="is_vat_payer" ${b.is_vat_payer ? 'checked' : ''} ${manage ? '' : 'disabled'}></div>
    <div class="switch"><span>${t('paysEsv')}</span><input type="checkbox" name="pays_esv" ${b.pays_esv ? 'checked' : ''} ${manage ? '' : 'disabled'}></div>
    ${manage ? `<button class="btn" type="submit" style="margin-top:10px">${t('save')}</button>` : ''}</form>`);
  if (can('read')) {
    const accRows = m.accounts.map(a => `<div class="row tap" data-acc="${a.id}"><span class="ic">${icon(a.bank ? 'bank' : 'wallet')}</span><span class="grow"><b>${esc(a.name)}</b><small>${a.bank === 'mono' ? 'monobank' : a.bank === 'privat' ? 'ПриватБанк' : ''}</small></span><span class="amt">${a.balance !== undefined ? money(a.balance) : ''}</span></div>`).join('');
    sections.push(listCard(t('accounts'), accRows, 'acc-add'));
    if (window.FB.bankCard) sections.push(window.FB.bankCard());
    if (window.FB.teamCard) sections.push(window.FB.teamCard());
    const cats = kind => m.categories.filter(c => c.kind === kind).map(c => `<div class="row tap" data-cat="${c.id}"><span class="ic ${kind === 'income' ? 'in' : 'out'}">${icon('tag')}</span><span class="grow"><b>${esc(c.name)}</b>${c.is_cogs ? `<small>${t('cogs')}</small>` : ''}</span></div>`).join('');
    sections.push(listCard(`${t('categories')} · ${t('incomeCats')}`, cats('income'), 'cat-add-income'));
    sections.push(listCard(`${t('categories')} · ${t('expenseCats')}`, cats('expense'), 'cat-add-expense'));
    sections.push(listCard(t('projects'), m.projects.map(p => `<div class="row tap" data-proj="${p.id}"><span class="ic">${icon('folder')}</span><span class="grow"><b>${esc(p.name)}</b>${p.archived ? '<small>archived</small>' : ''}</span></div>`).join(''), 'proj-add'));
    sections.push(listCard(t('counterparties'), m.counterparties.map(c => `<div class="row tap" data-cp="${c.id}"><span class="ic">${icon('person')}</span><span class="grow"><b>${esc(c.name)}</b><small>${t(c.kind + 'K')}${c.phone ? ' · ' + esc(c.phone) : ''}</small></span></div>`).join(''), 'cp-add'));
    sections.push(`<div id="rec-box"></div>`);
    if (window.FB.stockCard) sections.push(window.FB.stockCard());
  }
  sections.push(`<div class="section-head"><h2>${t('notifications')}</h2></div><div class="card">
    ${[['daily_digest','dailyDigest'],['weekly_digest','weeklyDigest'],['monthly_report','monthlyReport']].map(([k, l]) => `<label class="switch"><span>${t(l)}</span><input type="checkbox" data-notif="${k}" ${b[k] ? 'checked' : ''} ${manage ? '' : 'disabled'}></label>`).join('')}</div>`);
  sections.push(`<div class="section-head"><h2>${t('language')} · ${t('theme')}</h2></div><div class="card">
    <div class="seg" id="lang">${['uk','ru','en'].map(l => `<button type="button" data-l="${l}" class="${LANG === l ? 'on' : ''}">${{uk:'Українська',ru:'Русский',en:'English'}[l]}</button>`).join('')}</div>
    <div class="seg" id="theme" style="margin:0">${['system','light','dark'].map(x => `<button type="button" data-th="${x}" class="${(S.me.user.theme || 'system') === x ? 'on' : ''}">${t('theme' + x[0].toUpperCase() + x.slice(1))}</button>`).join('')}</div></div>`);
  if (window.FB.referralCard) sections.push(window.FB.referralCard());
  sections.push(`<p class="disclaimer" style="text-align:center">finplan Business · /paysupport · /terms</p>`);
  v.innerHTML = `<h1>${t('tabMore')}</h1>` + sections.join('');

  const bf = $('#bizf');
  bf.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      const body = {name: bf.name.value.trim(), kind: bf.kind.value, fop_group: Number(bf.fop_group.value), tax_rate: String(bf.tax_rate.value).replace(',', '.'),
        currency: bf.currency.value, is_vat_payer: bf.is_vat_payer.checked, pays_esv: bf.pays_esv.checked};
      S.me.business = {...S.me.business, ...(await patch('/business', body))}; renderTop(); toast(t('saved'));
    } catch (err) { errorToast(err); }
  });
  $$('[data-notif]', v).forEach(c => c.addEventListener('change', async () => { try { await patch('/business', {[c.dataset.notif]: c.checked}); S.me.business[c.dataset.notif] = c.checked; } catch (e) { errorToast(e); c.checked = !c.checked; } }));
  $$('[data-l]', v).forEach(bn => bn.addEventListener('click', async () => { LANG = bn.dataset.l; S.me.user.language = LANG; translateStatic(); renderTop(); patch('/me', {language: LANG}).catch(() => {}); TABS.more(); }));
  $$('[data-th]', v).forEach(bn => bn.addEventListener('click', () => { S.me.user.theme = bn.dataset.th; store.set('fb-theme', bn.dataset.th); patch('/me', {theme: bn.dataset.th}).catch(() => {}); applyTheme(); TABS.more(); }));
  if (!can('read')) return;
  const accForm = a => simpleForm(a ? a.name : t('accounts'), [{name:'name', label:t('name'), value: a && a.name}, {name:'opening_balance', label:t('opening'), value: a ? a.opening_balance : 0, mode:'decimal'}],
    body => a ? patch('/accounts/' + a.id, body) : post('/accounts', body), a && (() => del('/accounts/' + a.id)));
  $('#acc-add') && $('#acc-add').addEventListener('click', () => accForm());
  $$('[data-acc]', v).forEach(r => r.addEventListener('click', () => manage && accForm(byId(m.accounts, Number(r.dataset.acc)))));
  const catForm = (kind, c) => simpleForm(c ? c.name : t('category'), [{name:'name', label:t('name'), value: c && c.name}].concat(kind === 'expense' ? [{name:'is_cogs', label:t('cogs'), type:'check', value: c && c.is_cogs}] : []),
    body => c ? patch('/categories/' + c.id, body) : post('/categories', {...body, kind}), c && (() => del('/categories/' + c.id)));
  $('#cat-add-income') && $('#cat-add-income').addEventListener('click', () => catForm('income'));
  $('#cat-add-expense') && $('#cat-add-expense').addEventListener('click', () => catForm('expense'));
  $$('[data-cat]', v).forEach(r => r.addEventListener('click', () => { const c = byId(m.categories, Number(r.dataset.cat)); manage && catForm(c.kind, c); }));
  const projForm = p => simpleForm(p ? p.name : t('project'), [{name:'name', label:t('name'), value: p && p.name}].concat(p ? [{name:'archived', label:'Archive', type:'check', value: p.archived}] : []),
    body => p ? patch('/projects/' + p.id, body) : post('/projects', body));
  $('#proj-add') && $('#proj-add').addEventListener('click', () => projForm());
  $$('[data-proj]', v).forEach(r => r.addEventListener('click', () => manage && projForm(byId(m.projects, Number(r.dataset.proj)))));
  const cpForm = c => simpleForm(c ? c.name : t('counterparties'), [{name:'name', label:t('name'), value: c && c.name},
      {name:'kind', label:t('kind'), type:'select', options:[['client', t('clientK')], ['supplier', t('supplierK')], ['both', t('bothK')]], value: c ? c.kind : 'client'},
      {name:'phone', label:t('phone'), value: c && c.phone}, {name:'telegram_username', label:'Telegram', value: c && c.telegram_username}, {name:'tax_id', label:t('taxId'), value: c && c.tax_id}, {name:'note', label:t('note'), value: c && c.note}],
    body => c ? patch('/counterparties/' + c.id, body) : post('/counterparties', body), c && (() => del('/counterparties/' + c.id)));
  $('#cp-add') && $('#cp-add').addEventListener('click', () => cpForm());
  $$('[data-cp]', v).forEach(r => r.addEventListener('click', () => cpForm(byId(m.counterparties, Number(r.dataset.cp)))));
  renderRecurring($('#rec-box'));
  if (window.FB.afterMore) window.FB.afterMore(v);
};

async function renderRecurring(box){
  if (!box) return;
  let rows = []; try { rows = await api('/recurring'); } catch { return; }
  const m = S.meta;
  box.innerHTML = listCard(t('recurring'), rows.map(r => { const c = byId(m.categories, r.category_id);
    return `<div class="row tap" data-rec="${r.id}"><span class="ic ${r.kind === 'income' ? 'in' : 'out'}">${icon('repeat')}</span><span class="grow"><b>${esc(r.note || (c && c.name) || t(r.kind))}</b><small>${r.day_of_month} · ${t('next')}: ${fmtDate(r.next_date)}</small></span><span class="amt">${money(r.kind === 'income' ? r.amount : -r.amount, null, true)}</span></div>`; }).join(''), 'rec-add');
  const form = r => simpleForm(t('recurring'), [
      {name:'kind', label:t('kind'), type:'select', options:[['expense', t('expense')], ['income', t('income')]], value: r ? r.kind : 'expense'},
      {name:'amount', label:t('amount'), value: r && r.amount, mode:'decimal'}, {name:'day_of_month', label:t('dayOfMonth'), value: r ? r.day_of_month : 1, mode:'numeric'},
      {name:'category_id', label:t('category'), type:'select', options:[['', t('none')]].concat(m.categories.map(c => [c.id, (c.kind === 'income' ? '+ ' : '− ') + c.name])), value: r && r.category_id},
      {name:'account_id', label:t('account'), type:'select', options:[['', t('none')]].concat(m.accounts.map(a => [a.id, a.name])), value: r && r.account_id},
      {name:'note', label:t('note'), value: r && r.note}],
    body => { body.category_id = body.category_id ? Number(body.category_id) : null; body.account_id = body.account_id ? Number(body.account_id) : null; body.day_of_month = Number(body.day_of_month);
      return r ? patch('/recurring/' + r.id, body) : post('/recurring', body); }, r && (() => del('/recurring/' + r.id)));
  const add = $('#rec-add', box); add && add.addEventListener('click', () => form());
  $$('[data-rec]', box).forEach(x => x.addEventListener('click', () => can('manage') && form(rows.find(r => r.id === Number(x.dataset.rec)))));
}

/* A small generic form in a sheet: fields [{name,label,value,type,options,mode}] */
function simpleForm(title, fields, onSave, onDelete, extra){
  const html = `<h2>${esc(title)}<button class="icon-btn" id="x">${icon('x')}</button></h2><form id="sf">${fields.map(fd => {
    if (fd.type === 'check') return `<label class="switch"><span>${esc(fd.label)}</span><input type="checkbox" name="${fd.name}" ${fd.value ? 'checked' : ''}></label>`;
    if (fd.type === 'select') return `<label class="f">${esc(fd.label)}<select class="in" name="${fd.name}">${fd.options.map(([val, l]) => `<option value="${esc(val)}"${String(val) === String(fd.value ?? '') ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></label>`;
    if (fd.type === 'textarea') return `<label class="f">${esc(fd.label)}<textarea class="in" name="${fd.name}" rows="3">${esc(fd.value ?? '')}</textarea></label>`;
    return `<label class="f">${esc(fd.label)}<input class="in" name="${fd.name}" ${fd.type ? `type="${fd.type}"` : ''} ${fd.mode ? `inputmode="${fd.mode}"` : ''} value="${esc(fd.value ?? '')}" ${fd.required === false ? '' : (fd.name === 'name' ? 'required' : '')}></label>`;
  }).join('')}${extra || ''}<button class="btn" type="submit" style="margin-top:6px">${t('save')}</button>${onDelete ? `<button class="btn danger" type="button" id="sf-del" style="margin-top:8px">${icon('trash')} ${t('delete')}</button>` : ''}</form>`;
  openSheet(html, el => {
    $('#x', el).addEventListener('click', closeSheet);
    $('#sf', el).addEventListener('submit', async e => {
      e.preventDefault(); const body = {};
      fields.forEach(fd => { const input = e.target[fd.name]; if (!input) return; body[fd.name] = fd.type === 'check' ? input.checked : (fd.mode === 'decimal' ? String(input.value).replace(',', '.').replace(/\s/g, '') || '0' : (input.value.trim() === '' ? null : input.value.trim())); });
      try { await onSave(body); closeSheet(); toast(t('saved')); refresh(); } catch (err) { errorToast(err); }
    });
    const d = $('#sf-del', el); d && d.addEventListener('click', async () => { try { await onDelete(); closeSheet(); toast(t('deleted')); refresh(); } catch (err) { errorToast(err); } });
  });
}
window.FB.simpleForm = simpleForm;

/* ------------------------------------------------------------------ boot */
async function boot(){
  try { S.me = await api('/me'); }
  catch (e) {
    if (e.status === 403 && store.get('fb-business')) { try { localStorage.removeItem('fb-business'); } catch {} return boot(); }
    $('#view').innerHTML = `<div class="card empty" style="margin-top:40px">${icon('lock')}<div>${e.status === 401 ? t('offline') : t('err')}</div></div>`;
    return;
  }
  LANG = S.me.user.language || 'uk';
  if (S.me.business) store.set('fb-business', S.me.business.id);
  translateStatic(); applyTheme(); renderTop();
  if (!S.me.business) return renderOnboarding();
  try { S.meta = await api('/meta'); } catch (e) { return errorToast(e); }
  S.dash = null;
  const start = new URLSearchParams(location.search).get('tab') || (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || '';
  go(TABS[start] ? start : (can('read') ? 'home' : 'ops'));
  window.FB.onBoot && window.FB.onBoot();
}
window.FB.boot = boot;
window.FB.setLang = l => { LANG = l; };
window.FB.lang = () => LANG;
if (tg) { try { tg.ready(); tg.expand(); tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch {} }
applyTheme();
document.addEventListener('DOMContentLoaded', () => {});
setTimeout(boot, 0);
})();
