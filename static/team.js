/* Stage 4: team and roles, stock, referral. */
(function(){
'use strict';
const F = window.FB, {S, esc, icon, $, $$, api, post, patch, money, toast, openSheet, closeSheet, errorToast, can, opts} = F;
const L = () => F.lang();
const W = {
  uk:{team:'Команда',invite:'Запросити',inviteRole:'Роль',linkReady:'Посилання одноразове, діє 2 дні. Надішліть його людині:',share:'Поділитися',
    copy:'Копіювати',copied:'Скопійовано',pending:'Запрошення',until:'до {d}',seats:'{n} з {l} місць',remove:'Видалити з команди',leave:'Вийти з команди',
    teamLocked:'Працівники: у Pro — бухгалтер, у Team — до 10 людей з ролями.',roleHelp_staff:'лише додає операції',roleHelp_accountant:'бачить і вивантажує, без змін',
    roleHelp_admin:'усе, крім оплати',stock:'Склад',product:'Товар',unit:'Од.',cost:'Собівартість',salePrice:'Ціна продажу',qty:'Залишок',
    restock:'Надходження',restockQty:'Кількість',unitCost:'Ціна закупівлі за од.',recordExp:'Записати витрату',stockValue:'На складі на {v}',
    low:'закінчується',quantity:'Кількість',referral:'Запросіть друга',refText:'Друг отримає 14 днів Pro, а ви — +30 днів, коли він оплатить підписку.',
    refStats:'Запрошено: {i} · оплатили: {p}',stockLocked:'Склад — у Team.'},
  ru:{team:'Команда',invite:'Пригласить',inviteRole:'Роль',linkReady:'Ссылка одноразовая, действует 2 дня. Отправьте её человеку:',share:'Поделиться',
    copy:'Копировать',copied:'Скопировано',pending:'Приглашения',until:'до {d}',seats:'{n} из {l} мест',remove:'Удалить из команды',leave:'Выйти из команды',
    teamLocked:'Сотрудники: в Pro — бухгалтер, в Team — до 10 человек с ролями.',roleHelp_staff:'только добавляет операции',roleHelp_accountant:'видит и выгружает, без изменений',
    roleHelp_admin:'всё, кроме оплаты',stock:'Склад',product:'Товар',unit:'Ед.',cost:'Себестоимость',salePrice:'Цена продажи',qty:'Остаток',
    restock:'Поступление',restockQty:'Количество',unitCost:'Цена закупки за ед.',recordExp:'Записать расход',stockValue:'На складе на {v}',
    low:'заканчивается',quantity:'Количество',referral:'Пригласите друга',refText:'Друг получит 14 дней Pro, а вы — +30 дней, когда он оплатит подписку.',
    refStats:'Приглашено: {i} · оплатили: {p}',stockLocked:'Склад — в Team.'},
};
W.en = Object.assign({}, W.uk, {team:'Team',invite:'Invite',stock:'Stock',referral:'Invite a friend'});
const w = (k, v) => { let s = (W[L()] || W.uk)[k] ?? W.uk[k] ?? k; if (v) for (const [a, b] of Object.entries(v)) s = s.replace('{' + a + '}', b); return s; };
const tg = window.Telegram && Telegram.WebApp;
const roleName = r => F.t('role_' + r);

function shareLink(link, text){
  if (tg && tg.openTelegramLink) tg.openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(link) + '&text=' + encodeURIComponent(text || ''));
  else window.open(link, '_blank');
}
async function copy(text){ try { await navigator.clipboard.writeText(text); toast(w('copied')); } catch { toast(text); } }

/* ------------------------------------------------------------------ team */
F.teamCard = () => `<div id="team-box"></div>`;
const baseAfterMore = F.afterMore;
F.afterMore = v => { baseAfterMore && baseAfterMore(v); renderTeam($('#team-box', v)); renderStock($('#stock-box', v)); renderReferral($('#ref-box', v)); };

async function renderTeam(box){
  if (!box) return;
  let d; try { d = await api('/team'); } catch { return; }
  const allowed = d.roles.filter(r => r !== 'owner');
  box.innerHTML = `<div class="section-head"><h2>${w('team')}</h2><span class="muted small">${w('seats', {n: d.members.length + d.invites.length, l: d.limit})}</span></div><div class="card">
    ${d.members.map(m => `<div class="row tap" data-m="${m.id}"><span class="ic">${icon('person')}</span><span class="grow"><b>${esc(m.name || '—')}${m.me ? ' ·  ✓' : ''}</b><small>${roleName(m.role)}</small></span></div>`).join('')}
    ${d.invites.map(i => `<div class="row tap" data-i="${i.id}"><span class="ic warn">${icon('send')}</span><span class="grow"><b>${w('pending')}: ${roleName(i.role)}</b><small>${w('until', {d: F.fmtDate(i.expires_at.slice(0, 10))})}</small></span><button class="icon-btn" data-ix="${i.id}">${icon('x')}</button></div>`).join('')}
    ${d.can_manage ? (allowed.length ? `<button class="btn" id="invite" style="margin-top:12px">${icon('users')} ${w('invite')}</button>` :
      `<p class="hint">${w('teamLocked')}</p><button class="btn pro" id="team-up" style="margin-top:8px">${icon('star')} Team</button>`) : ''}</div>`;
  const up = $('#team-up', box); if (up) up.onclick = () => F.planSheet({plan_needed: 'pro', feature: 'members'});
  const inv = $('#invite', box); if (inv) inv.onclick = () => inviteSheet(allowed, box);
  $$('[data-ix]', box).forEach(b => b.onclick = async e => { e.stopPropagation(); try { await F.del('/team/invites/' + b.dataset.ix); renderTeam(box); } catch (err) { errorToast(err); } });
  $$('[data-i]', box).forEach(r => r.onclick = () => { const i = d.invites.find(x => x.id === Number(r.dataset.i)); if (i && i.link) linkSheet(i.link, i.role); });
  $$('[data-m]', box).forEach(r => r.onclick = () => { const m = d.members.find(x => x.id === Number(r.dataset.m)); memberSheet(m, d, allowed, box); });
}

function inviteSheet(allowed, box){
  openSheet(`<h2>${w('invite')}<button class="icon-btn" id="x">${icon('x')}</button></h2>
    <div class="card flat">${allowed.map(r => `<div class="row tap" data-r="${r}"><span class="ic">${icon('person')}</span><span class="grow"><b>${roleName(r)}</b><small>${w('roleHelp_' + r)}</small></span>${icon('chev', 'i chev')}</div>`).join('')}</div>`, el => {
    $('#x', el).onclick = closeSheet;
    $$('[data-r]', el).forEach(r => r.onclick = async () => {
      try { const i = await post('/team/invites', {role: r.dataset.r}); closeSheet(); setTimeout(() => linkSheet(i.link, i.role), 250); renderTeam(box); }
      catch (e) { errorToast(e); }
    });
  });
}

function linkSheet(link, role){
  openSheet(`<h2>${roleName(role)}<button class="icon-btn" id="x">${icon('x')}</button></h2><p class="hint" style="margin-top:0">${w('linkReady')}</p>
    <div class="card flat" style="font-size:13px;overflow-wrap:anywhere">${esc(link)}</div>
    <div class="btn-row"><button class="btn" id="share">${icon('send')} ${w('share')}</button><button class="btn ghost" id="copy">${w('copy')}</button></div>`, el => {
    $('#x', el).onclick = closeSheet;
    $('#share', el).onclick = () => shareLink(link, 'finplan Business');
    $('#copy', el).onclick = () => copy(link);
  });
}

function memberSheet(m, d, allowed, box){
  if (m.role === 'owner') return;
  const canEdit = d.can_manage && !m.me;
  openSheet(`<h2>${esc(m.name || '—')}<button class="icon-btn" id="x">${icon('x')}</button></h2>
    ${canEdit ? `<div class="seg">${allowed.map(r => `<button type="button" data-role="${r}" class="${m.role === r ? 'on' : ''}">${roleName(r)}</button>`).join('')}</div>` : `<p>${roleName(m.role)}</p>`}
    ${canEdit || m.me ? `<button class="btn danger" id="rm">${icon('trash')} ${m.me ? w('leave') : w('remove')}</button>` : ''}`, el => {
    $('#x', el).onclick = closeSheet;
    $$('[data-role]', el).forEach(b => b.onclick = async () => { try { await patch('/team/members/' + m.id, {role: b.dataset.role}); closeSheet(); renderTeam(box); } catch (e) { errorToast(e); } });
    const rm = $('#rm', el); if (rm) rm.onclick = async () => { try { await F.del('/team/members/' + m.id); closeSheet(); if (m.me) { try { localStorage.removeItem('fb-business'); } catch {} F.boot(); } else renderTeam(box); } catch (e) { errorToast(e); } };
  });
}

/* ------------------------------------------------------------------ stock */
F.stockCard = () => `<div id="stock-box"></div>`;
async function loadProducts(){ try { S.products = await api('/products'); } catch { S.products = null; } return S.products; }

async function renderStock(box){
  if (!box) return;
  if (!S.me.plan.limits.stock) {
    box.innerHTML = `<div class="section-head"><h2>${w('stock')}</h2></div><button class="card ask" id="stock-up">${icon('box')}<span>${w('stockLocked')}</span><span class="lock" style="margin-left:auto">${icon('lock')}</span></button>`;
    $('#stock-up', box).onclick = () => F.planSheet({plan_needed: 'team', feature: 'stock'});
    return;
  }
  const rows = await loadProducts() || [];
  const total = rows.reduce((a, p) => a + Number(p.stock_value), 0);
  box.innerHTML = F.listCard(w('stock'), rows.map(p => `<div class="row tap" data-p="${p.id}"><span class="ic">${icon('box')}</span><span class="grow"><b>${esc(p.name)}</b><small>${w('cost')}: ${money(p.cost_price)} · ${w('salePrice')}: ${money(p.sale_price)}</small></span>
    <span style="display:grid;justify-items:end;gap:3px"><span class="amt">${Number(p.stock_qty)} ${esc(p.unit)}</span>${Number(p.stock_qty) <= 2 ? `<span class="pill bad">${w('low')}</span>` : ''}</span></div>`).join(''), 'prod-add')
    + (rows.length ? `<p class="hint">${w('stockValue', {v: money(total)})}</p>` : '');
  const form = p => F.simpleForm(p ? p.name : w('product'), [{name:'name', label:F.t('name'), value: p && p.name}, {name:'unit', label:w('unit'), value: p ? p.unit : 'шт'},
      {name:'cost_price', label:w('cost'), mode:'decimal', value: p ? p.cost_price : ''}, {name:'sale_price', label:w('salePrice'), mode:'decimal', value: p ? p.sale_price : ''},
      {name:'stock_qty', label:w('qty'), mode:'decimal', value: p ? p.stock_qty : 0}],
    body => p ? patch('/products/' + p.id, body) : post('/products', body), null,
    p && can('write') ? `<button class="btn ghost" type="button" id="restock" style="margin-bottom:8px">${icon('plus')} ${w('restock')}</button>` : '');
  const add = $('#prod-add', box); if (add) add.onclick = () => form();
  $$('[data-p]', box).forEach(r => r.onclick = () => {
    const p = rows.find(x => x.id === Number(r.dataset.p)); if (!can('manage')) return;
    form(p);
    setTimeout(() => { const b = $('#restock'); if (b) b.onclick = () => { closeSheet(); setTimeout(() => restockForm(p), 250); }; }, 50);
  });
}
function restockForm(p){
  F.simpleForm(`${w('restock')}: ${p.name}`, [{name:'quantity', label:w('restockQty'), mode:'decimal'}, {name:'unit_cost', label:w('unitCost'), mode:'decimal', value: p.cost_price},
    {name:'record_expense', label:w('recordExp'), type:'check', value: true}], body => post(`/products/${p.id}/restock`, body));
}

F.productField = op => {
  if (!S.me.plan.limits.stock || !S.products || !S.products.length) return '';
  return `<div class="grid2" data-for="income expense"><label class="f">${w('product')}<select class="in" name="product_id">${opts(S.products.filter(p => !p.archived), op.product_id, F.t('none'))}</select></label>
    <label class="f">${w('quantity')}<input class="in" name="quantity" inputmode="decimal" value="${op.quantity ? Number(op.quantity) : 1}"></label></div>`;
};
const baseBoot = F.onBoot;
F.onBoot = () => { baseBoot && baseBoot(); if (S.me.plan.limits.stock) loadProducts(); };

/* ------------------------------------------------------------------ referral */
F.referralCard = () => can('billing') ? `<div id="ref-box"></div>` : '';
async function renderReferral(box){
  if (!box) return;
  let d; try { d = await api('/referral'); } catch { return; }
  if (!d.link) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="section-head"><h2>${w('referral')}</h2></div><div class="card"><div class="row" style="padding-top:0"><span class="ic">${icon('gift')}</span><span class="grow" style="white-space:normal"><small style="white-space:normal">${w('refText')}</small></span></div>
    <div class="small muted" style="margin:6px 0 10px">${w('refStats', {i: d.invited, p: d.paid})}</div>
    <div class="btn-row" style="margin-top:0"><button class="btn" id="ref-share">${icon('send')} ${w('share')}</button><button class="btn ghost" id="ref-copy">${w('copy')}</button></div></div>`;
  $('#ref-share', box).onclick = () => shareLink(d.link, 'finplan Business — облік і податки для ФОП у Telegram');
  $('#ref-copy', box).onclick = () => copy(d.link);
}
})();
