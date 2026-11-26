/* Stage 3: AI assistant screen, bank connections, receipt photos. */
(function(){
'use strict';
const F = window.FB, {S, esc, icon, $, $$, api, post, money, toast, openSheet, closeSheet, errorToast, can, opts} = F;
const L = () => F.lang();
const W = {
  uk:{ask:'Запитати finplan…',title:'ШІ-асистент',hint:'Запитайте про продажі, витрати, податки — або опишіть операції словами чи надішліть фото чека боту.',
    examples:['Скільки я заробив цього місяця?','Який клієнт приніс найбільше?','вчора продала 3 торти по 450 і купила пакування на 300'],
    send:'Надіслати',confirm:'Записати',reject:'Відхилити',done:'Записано',rejected:'Відхилено',usage:'{u} з {l} запитів цього місяця',
    unlimited:'{u} запитів цього місяця',off:'ШІ-асистент ще не налаштований на сервері.',limit:'Ліміт запитів вичерпано',
    banks:'Банки',mono:'monobank',privat:'ПриватБанк (Автоклієнт)',connect:'Підключити',monoToken:'Особистий токен monobank',
    monoHelp:'Отримайте токен на api.monobank.ua (вхід через застосунок банку). Токен зберігається зашифровано й нікуди не передається.',
    pickAcc:'Оберіть рахунок ФОП',syncNow:'Оновити',lastSync:'Оновлено {d}',disconnect:'Відключити',imported:'Імпортовано: {n}',
    privatId:'ID клієнта (Автоклієнт)',privatToken:'Токен Автоклієнта',iban:'IBAN рахунку',privatHelp:'Підключення в Приват24 для бізнесу → Автоклієнт. Ця інтеграція ще не перевірена на реальному рахунку.',
    photo:'Фото чека в чат',thinking:'Думаю…'},
  ru:{ask:'Спросить finplan…',title:'ИИ-ассистент',hint:'Спросите о продажах, расходах, налогах — или опишите операции словами либо пришлите фото чека боту.',
    examples:['Сколько я заработал в этом месяце?','Какой клиент принёс больше всего?','вчера продала 3 торта по 450 и купила упаковку на 300'],
    send:'Отправить',confirm:'Записать',reject:'Отклонить',done:'Записано',rejected:'Отклонено',usage:'{u} из {l} запросов в этом месяце',
    unlimited:'{u} запросов в этом месяце',off:'ИИ-ассистент пока не настроен на сервере.',limit:'Лимит запросов исчерпан',
    banks:'Банки',mono:'monobank',privat:'ПриватБанк (Автоклиент)',connect:'Подключить',monoToken:'Личный токен monobank',
    monoHelp:'Получите токен на api.monobank.ua (вход через приложение банка). Токен хранится зашифрованным и никуда не передаётся.',
    pickAcc:'Выберите счёт ФОП',syncNow:'Обновить',lastSync:'Обновлено {d}',disconnect:'Отключить',imported:'Импортировано: {n}',
    privatId:'ID клиента (Автоклиент)',privatToken:'Токен Автоклиента',iban:'IBAN счёта',privatHelp:'Подключение в Приват24 для бизнеса → Автоклиент. Эта интеграция ещё не проверена на реальном счёте.',
    photo:'Фото чека в чат',thinking:'Думаю…'},
};
W.en = Object.assign({}, W.uk, {ask:'Ask finplan…',title:'AI assistant',send:'Send',confirm:'Save',reject:'Reject',banks:'Banks',connect:'Connect'});
const w = (k, v) => { let s = (W[L()] || W.uk)[k] ?? W.uk[k] ?? k; if (v && typeof s === 'string') for (const [a, b] of Object.entries(v)) s = s.replace('{' + a + '}', b); return s; };

/* ------------------------------------------------------------------ AI */
F.askRow = () => `<button class="card ask" id="ask-ai">${icon('spark')}<span>${w('ask')}</span></button>`;
const baseAfterHome = F.afterHome;
F.afterHome = v => { const a = $('#ask-ai', v); if (a) a.onclick = () => F.go('ai'); baseAfterHome && baseAfterHome(v); };
S.chat = S.chat || [];

F.TABS.ai = async function(){
  const v = $('#view');
  v.innerHTML = `<h1>${w('title')}</h1><div id="usage" class="hint" style="margin:-6px 2px 12px"></div><div class="chat" id="chat"></div>
    <div id="examples" class="chips"></div>
    <form id="askf" class="card flat" style="display:flex;gap:8px;align-items:flex-end;padding:8px">
      <textarea class="in" name="q" rows="1" style="border:0;background:none;resize:none;max-height:120px" placeholder="${w('ask')}"></textarea>
      <button class="icon-btn" style="background:var(--primary);color:var(--on-primary);border:0" aria-label="${w('send')}">${icon('send')}</button></form>
    <p class="hint">${w('hint')}</p>`;
  const usage = async () => { try { const u = await api('/ai/usage'); $('#usage').textContent = !u.enabled ? w('off') : u.limit === null ? w('unlimited', {u: u.used}) : w('usage', {u: u.used, l: u.limit}); } catch {} };
  usage();
  renderChat();
  $('#examples').innerHTML = S.chat.length ? '' : w('examples').map(e => `<button class="chip" data-ex="${esc(e)}">${esc(e)}</button>`).join('');
  $$('[data-ex]', v).forEach(b => b.onclick = () => { $('#askf').q.value = b.dataset.ex; $('#askf').requestSubmit(); });
  const f = $('#askf'), ta = f.q;
  ta.oninput = () => { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'; };
  ta.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); f.requestSubmit(); } };
  f.onsubmit = async e => {
    e.preventDefault();
    const q = ta.value.trim(); if (!q) return;
    ta.value = ''; ta.style.height = 'auto'; $('#examples').innerHTML = '';
    const history = S.chat.filter(m => m.text).slice(-8).map(m => ({role: m.role, text: m.text}));
    S.chat.push({role:'user', text:q}); S.chat.push({role:'assistant', text:w('thinking'), pending:true}); renderChat();
    try {
      const r = await post('/ai/chat', {message: q, history});
      S.chat.pop(); S.chat.push({role:'assistant', text:r.text, drafts:r.drafts});
    } catch (err) {
      S.chat.pop(); S.chat.push({role:'assistant', text: err.status === 402 ? w('limit') : (err.message || F.t('err'))});
      if (err.status !== 402) errorToast(err);
    }
    renderChat(); usage();
  };
};

function renderChat(){
  const box = $('#chat'); if (!box) return;
  box.innerHTML = S.chat.map((m, i) => `<div class="msg ${m.role === 'user' ? 'me' : 'ai'}"${m.pending ? ' style="opacity:.6"' : ''}><div class="mt">${esc(m.text)}</div>${(m.drafts || []).map(d => `
    <div class="draft" data-draft="${d.id}" data-msg="${i}"><div style="white-space:pre-wrap">${esc(d.text)}</div>
      ${d.status ? `<div class="pill ${d.status === 'done' ? 'ok' : ''}" style="margin-top:8px">${d.status === 'done' ? w('done') : w('rejected')}</div>` :
      `<div class="btn-row"><button class="btn" data-ok>${icon('check')} ${w('confirm')}</button><button class="btn ghost" data-no>${w('reject')}</button></div>`}</div>`).join('')}</div>`).join('');
  $$('[data-draft]', box).forEach(el => {
    const msg = S.chat[Number(el.dataset.msg)], d = msg.drafts.find(x => x.id === Number(el.dataset.draft));
    const act = async kind => { try { await post(`/ai/drafts/${d.id}/${kind}`); d.status = kind === 'confirm' ? 'done' : 'rejected'; if (kind === 'confirm') { S.meta = await api('/meta'); S.dash = null; } renderChat(); } catch (e) { errorToast(e); } };
    const ok = $('[data-ok]', el), no = $('[data-no]', el);
    if (ok) ok.onclick = () => act('confirm');
    if (no) no.onclick = () => act('reject');
  });
  box.lastElementChild && box.lastElementChild.scrollIntoView({block:'end', behavior:'smooth'});
}

/* ------------------------------------------------------------------ banks */
F.bankCard = () => `<div id="bank-box"></div>`;
const baseAfterMore = F.afterMore;
F.afterMore = v => { baseAfterMore && baseAfterMore(v); renderBanks($('#bank-box', v)); };
const fmtDT = d => d ? new Date(d.endsWith('Z') ? d : d + 'Z').toLocaleString({uk:'uk-UA', ru:'ru-RU', en:'en-GB'}[L()], {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}) : '—';

async function renderBanks(box){
  if (!box) return;
  let rows = []; try { rows = await api('/banks'); } catch { return; }
  const pro = S.me.plan.limits.banks;
  const lock = pro ? '' : ` <span class="lock">${icon('lock')}</span>`;
  box.innerHTML = `<div class="section-head"><h2>${w('banks')}</h2></div><div class="card">
    ${rows.map(c => `<div class="row"><span class="ic">${icon('bank')}</span><span class="grow"><b>${esc(c.account_label || c.bank)}</b><small class="${c.last_error ? 'neg' : ''}">${esc(c.last_error || w('lastSync', {d: fmtDT(c.last_sync_at)}))}</small></span>
      ${can('write') ? `<button class="chip" data-sync="${c.id}">${w('syncNow')}</button>` : ''}${can('manage') ? `<button class="icon-btn" data-off="${c.id}" style="margin-left:6px">${icon('x')}</button>` : ''}</div>`).join('')}
    ${can('manage') ? `<div class="btn-row" style="margin-top:${rows.length ? 12 : 0}px"><button class="btn ghost" id="mono-add">${w('mono')}${lock}</button><button class="btn ghost" id="privat-add">ПриватБанк${lock}</button></div>` : ''}</div>`;
  const gate = fn => () => pro ? fn() : F.planSheet({plan_needed: 'pro', feature: 'banks'});
  const m = $('#mono-add', box); if (m) m.onclick = gate(monoSheet);
  const p = $('#privat-add', box); if (p) p.onclick = gate(privatSheet);
  $$('[data-sync]', box).forEach(b => b.onclick = async () => { b.disabled = true; try { const r = await post(`/banks/${b.dataset.sync}/sync`); toast(w('imported', {n: r.imported})); F.refresh(); } catch (e) { errorToast(e); b.disabled = false; } });
  $$('[data-off]', box).forEach(b => b.onclick = async () => { try { await F.del('/banks/' + b.dataset.off); renderBanks(box); } catch (e) { errorToast(e); } });
}

function monoSheet(){
  openSheet(`<h2>${w('mono')}<button class="icon-btn" id="x">${icon('x')}</button></h2>
    <form id="mf"><label class="f">${w('monoToken')}<input class="in" name="token" autocomplete="off" required minlength="20"></label>
    <p class="hint" style="margin-top:-4px">${w('monoHelp')}</p><div id="accs"></div><button class="btn" type="submit" style="margin-top:12px">${w('connect')}</button></form>`, el => {
    $('#x', el).onclick = closeSheet;
    const f = $('#mf', el); let accounts = null;
    f.onsubmit = async e => {
      e.preventDefault();
      const btn = f.querySelector('button[type=submit]'); btn.disabled = true;
      try {
        if (!accounts) {
          accounts = await post('/banks/mono/accounts', {token: f.token.value.trim()});
          $('#accs', el).innerHTML = `<label class="f" style="margin-top:12px">${w('pickAcc')}<select class="in" name="acc">${accounts.map(a => `<option value="${esc(a.id)}">${esc((a.is_fop ? 'ФОП · ' : '') + a.currency + ' · ' + (a.iban || a.masked || a.id))}</option>`).join('')}</select></label>`;
        } else {
          const acc = accounts.find(a => a.id === f.acc.value);
          const r = await post('/banks/mono', {token: f.token.value.trim(), account_external_id: acc.id, account_label: `monobank ${acc.is_fop ? 'ФОП ' : ''}${acc.currency}`});
          closeSheet(); toast(w('imported', {n: r.imported})); F.refresh();
        }
      } catch (err) { errorToast(err); }
      btn.disabled = false;
    };
  });
}

function privatSheet(){
  F.simpleForm(w('privat'), [{name:'client_id', label:w('privatId')}, {name:'token', label:w('privatToken')}, {name:'iban', label:w('iban')}],
    body => post('/banks/privat', body), null, `<p class="hint">${w('privatHelp')}</p>`);
}

/* ------------------------------------------------------------------ receipt photo on an operation */
const baseOpForm = F.opForm;
F.opForm = function(op){
  baseOpForm(op);
  if (op && op.has_attachment) {
    const f = $('#opf'); if (!f) return;
    const b = document.createElement('button'); b.type = 'button'; b.className = 'btn ghost'; b.style.marginTop = '8px';
    b.innerHTML = `${icon('camera')} ${w('photo')}`;
    b.onclick = async () => { try { await post(`/operations/${op.id}/photo`); toast('OK'); } catch (e) { errorToast(e); } };
    f.appendChild(b);
  }
};
})();
