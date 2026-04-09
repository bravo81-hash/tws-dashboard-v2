// ========================================================================================
// --- STRATEGY BUILDER STATE AND UI LOGIC ---
// ========================================================================================
const API_BASE_URL = "http://127.0.0.1:5001";
let builderState = {
    symbol: '', 
    underlyingPrice: null, 
    selectedExpiry: '', 
    expiries: [], 
    chain: [],
    chainMeta: null,
    legs: [], 
    priceSource: 'MID', 
    quoteFilter: 'ALL',
    chainWindow: 10,
    offset: 0, 
    commission: 0.65, 
    tPlusDays: 0, 
    ivShift: 0,
    account: '',
    accounts: []
};
let builderChart = null;
const BUILDER_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function s(id) { return document.getElementById(id); }
function formatNum(v,d=2) { return (typeof v === 'number' && !isNaN(v)) ? v.toFixed(d) : '---';}
function formatCurrency(v, showSign = false) {
    if (v === "Unlimited") return `<span class="font-semibold text-primary">Unlimited</span>`;
    if (typeof v !== 'number' || isNaN(v)) return '---';
    const sign = v >= 0 ? (showSign ? '+' : '') : '-';
    const color = v >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400';
    return `<span class="${color}">${sign}${Math.abs(v).toLocaleString('en-US', { style: 'currency', currency: 'USD' })}</span>`;
}

function parseNum(value, fallback = 0) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function formatCompactCount(value) {
    const parsed = Number.parseFloat(value);
    if (!Number.isFinite(parsed)) return '—';
    const abs = Math.abs(parsed);
    if (abs >= 1_000_000) return `${(parsed / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return `${(parsed / 1_000).toFixed(2)}K`;
    return `${Math.round(parsed)}`;
}

function finitePositive(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function parseBuilderExpiryDate(expiryRaw) {
    const expiry = String(expiryRaw || '').trim();
    if (!/^\d{8}$/.test(expiry)) return null;
    const year = Number.parseInt(expiry.slice(0, 4), 10);
    const month = Number.parseInt(expiry.slice(4, 6), 10) - 1;
    const day = Number.parseInt(expiry.slice(6, 8), 10);
    if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
    return new Date(year, month, day, 17, 0, 0, 0);
}

function calculateBuilderDte(expiryRaw) {
    const expiryDate = parseBuilderExpiryDate(expiryRaw);
    if (!expiryDate) return null;
    const msPerDay = 24 * 60 * 60 * 1000;
    const dte = Math.ceil((expiryDate - new Date()) / msPerDay);
    return Math.max(0, Number.isFinite(dte) ? dte : 0);
}

function formatBuilderExpiryLabel(expiryRaw) {
    const expiry = String(expiryRaw || '').trim();
    const expiryDate = parseBuilderExpiryDate(expiry);
    if (!expiryDate) return expiry;

    const day = String(expiryDate.getDate()).padStart(2, '0');
    const month = BUILDER_MONTH_NAMES[expiryDate.getMonth()] || '---';
    const year = String(expiryDate.getFullYear()).slice(2);
    const dte = calculateBuilderDte(expiry);
    const dteText = dte == null ? '— DTE' : `${dte} DTE`;

    return `${day}-${month}-${year} (${dteText})`;
}

function getLegQuoteForPriceSource(opt) {
    if (!opt) return 0;
    const mark = finitePositive(opt.mid) ?? 0;
    if (builderState.priceSource === 'BID') return finitePositive(opt.bid) ?? mark;
    if (builderState.priceSource === 'ASK') return finitePositive(opt.ask) ?? mark;
    return mark;
}

function estimateBuilderNetLimitPrice() {
    if (!Array.isArray(builderState.legs) || builderState.legs.length === 0) return 0;
    const net = builderState.legs.reduce((sum, leg) => {
        const sideSign = leg.side === 'BUY' ? 1 : -1;
        return sum + (sideSign * parseNum(leg.price, 0) * Math.abs(parseNum(leg.qty, 0)));
    }, 0);
    return Number(net.toFixed(2));
}

function maybeAutoFillBuilderLimitPrice(force = false) {
    const input = s('builder-limit-price');
    if (!input) return;
    const autoMode = input.dataset.autoMode !== 'manual';
    if (!force && !autoMode) return;
    input.value = estimateBuilderNetLimitPrice().toFixed(2);
    input.dataset.autoMode = 'auto';
}

function bindClick(id, handler) {
    const node = s(id);
    if (!node) return;
    node.onclick = handler;
}

function resetBuilderChartControls() {
    builderState.tPlusDays = 0;
    builderState.ivShift = 0;
    if (s('builder-date-slider')) s('builder-date-slider').value = '0';
    if (s('builder-iv-slider')) s('builder-iv-slider').value = '0';
    if (s('builder-date-label')) s('builder-date-label').textContent = 'T+0';
    if (s('builder-iv-label')) s('builder-iv-label').textContent = '+0%';
}

function clearBuilderWorkingSet() {
    builderState.selectedExpiry = '';
    builderState.expiries = [];
    builderState.chain = [];
    builderState.chainMeta = null;
    builderState.legs = [];
    builderState.underlyingPrice = null;
    resetBuilderChartControls();
    populateExpiryDropdown([]);
    renderChainTable([]);
    renderBuilderLegs();
    drawBuilderChart(null);
    updateBuilderMetrics(null);
    updateUndSummary();
    updateChainDiagnostics(null, []);
    maybeAutoFillBuilderLimitPrice(true);
}

function repriceBuilderLegsFromChain() {
    if (!Array.isArray(builderState.legs) || builderState.legs.length === 0) return;
    builderState.legs = builderState.legs.map((leg) => {
        if (leg.expiry !== builderState.selectedExpiry) return leg;
        const row = builderState.chain.find((r) => Number(r.strike) === Number(leg.strike));
        const opt = leg.right === 'C' ? row?.call : row?.put;
        if (!opt || !opt.conId) return leg;
        return {
            ...leg,
            conId: opt.conId,
            iv: parseNum(opt.iv, leg.iv || 0),
            price: getLegQuoteForPriceSource(opt)
        };
    });
}

function populateBuilderAccountSelect(accounts, preferredAccount = '') {
    const select = s('builder-account-select');
    if (!select) return;
    const sanitized = Array.from(new Set((accounts || []).map((x) => String(x || '').trim()).filter(Boolean))).sort();
    builderState.accounts = sanitized;

    const options = ['<option value="">— Select Account —</option>']
        .concat(sanitized.map((account) => `<option value="${account}">${account}</option>`));
    select.innerHTML = options.join('');

    const nextAccount = sanitized.includes(preferredAccount)
        ? preferredAccount
        : (sanitized.includes(builderState.account) ? builderState.account : (sanitized[0] || ''));

    builderState.account = nextAccount;
    select.value = nextAccount;
}

async function loadBuilderAccounts() {
    try {
        const response = await fetch(`${API_BASE_URL}/get_account_risk_context`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ selected_account: 'All', legs: [] })
        });
        if (response.ok) {
            const payload = await response.json();
            if (Array.isArray(payload.accounts) && payload.accounts.length > 0) {
                populateBuilderAccountSelect(payload.accounts, payload.selected_account === 'All' ? '' : payload.selected_account);
                return;
            }
        }
    } catch (error) {
        console.warn('Builder account context unavailable:', error);
    }

    try {
        const response = await fetch(`${API_BASE_URL}/data`);
        if (!response.ok) return;
        const positions = await response.json();
        const accounts = Array.isArray(positions)
            ? positions.map((row) => String(row.account || '').trim()).filter(Boolean)
            : [];
        populateBuilderAccountSelect(accounts);
    } catch (error) {
        console.warn('Builder account fallback unavailable:', error);
    }
}


function initBuilderUI() {
    s('builder-search-btn').onclick = onBuilderSearch;
    s('builder-account-select').onchange = () => {
        builderState.account = s('builder-account-select').value;
    };
    s('builder-expiry-select').onchange = () => { 
        builderState.selectedExpiry = s('builder-expiry-select').value; 
        if (builderState.symbol && builderState.selectedExpiry) {
            loadOptionChain(builderState.symbol, builderState.selectedExpiry, builderState.chainWindow);
        }
    };
    s('builder-chain-window').onchange = () => {
        const nextWindow = Math.max(2, Math.min(30, Number.parseInt(s('builder-chain-window').value, 10) || 10));
        builderState.chainWindow = nextWindow;
        if (builderState.symbol && builderState.selectedExpiry) {
            loadOptionChain(builderState.symbol, builderState.selectedExpiry, builderState.chainWindow);
        }
    };
    s('builder-price-source').onchange = () => {
        builderState.priceSource = s('builder-price-source').value;
        repriceBuilderLegsFromChain();
        renderBuilderLegs();
        maybeAutoFillBuilderLimitPrice();
        refreshBuilderChart();
    };
    s('builder-quote-filter').onchange = () => {
        builderState.quoteFilter = s('builder-quote-filter').value || 'ALL';
        renderChainTable(builderState.chain);
    };
    s('builder-offset').oninput = () => {
        builderState.offset = parseNum(s('builder-offset').value, 0);
        refreshBuilderChart();
    };
    s('builder-commission').oninput = () => {
        builderState.commission = parseNum(s('builder-commission').value, 0);
        refreshBuilderChart();
    };
    s('builder-date-slider').oninput = () => {
        builderState.tPlusDays = Number.parseInt(s('builder-date-slider').value, 10) || 0;
        s('builder-date-label').textContent = `T+${builderState.tPlusDays}`;
        refreshBuilderChart();
    };
    s('builder-iv-slider').oninput = () => {
        const v = Number.parseInt(s('builder-iv-slider').value, 10) || 0;
        builderState.ivShift = v / 100.0;
        s('builder-iv-label').textContent = `${v >= 0 ? '+' : ''}${v}%`;
        refreshBuilderChart();
    };
    s('builder-limit-price').oninput = () => {
        s('builder-limit-price').dataset.autoMode = 'manual';
    };

    const clearHandler = () => clearBuilder();
    const placeHandler = () => placeBuilderOrder();
    ['builder-clear-btn', 'builder-clear-btn-mobile'].forEach((id) => bindClick(id, clearHandler));
    ['builder-place-btn', 'builder-place-btn-mobile'].forEach((id) => bindClick(id, placeHandler));

    renderChainTable([]); 
    renderBuilderLegs(); 
    updateBuilderMetrics(null);
    updateChainDiagnostics(null, []);
    maybeAutoFillBuilderLimitPrice(true);
    void loadBuilderAccounts();
}

async function onBuilderSearch() {
    const symInput = s('builder-symbol-input');
    const sym = symInput.value.trim().toUpperCase();
    if (!sym) return;
    void loadBuilderAccounts();

    if (builderState.symbol && builderState.symbol !== sym) {
        clearBuilderWorkingSet();
    }
    builderState.symbol = sym;
    setBuilderStatus('Loading expiries...');
    const btn = s('builder-search-btn');
    btn.disabled = true;
    btn.textContent = 'Loading...';

    try {
        const res = await fetch(`${API_BASE_URL}/get_expiries?symbol=${encodeURIComponent(sym)}`);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Failed to load expiries.');
        }
        const data = await res.json();
        
        builderState.expiries = data.expiries || [];
        builderState.underlyingPrice = data.undPrice || null;
        populateExpiryDropdown(builderState.expiries);
        updateUndSummary();
        setBuilderStatus('Select an expiry to load the chain.');
    } catch (e) {
        setBuilderStatus(`Error: ${e.message}`);
        console.error(e);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Load Chain';
    }
}

function populateExpiryDropdown(expiries) {
    const select = s('builder-expiry-select');
    const sorted = (expiries || []).map((value) => String(value)).sort((a, b) => a.localeCompare(b));
    select.innerHTML = '<option value="">— Select Expiry —</option>' + sorted
        .map((expiry) => `<option value="${expiry}">${formatBuilderExpiryLabel(expiry)}</option>`)
        .join('');
    builderState.selectedExpiry = '';
}

function updateChainDiagnostics(meta, rows = []) {
    const contractsEl = s('builder-chain-contracts');
    const coverageEl = s('builder-chain-coverage');

    if (contractsEl) {
        if (!meta || typeof meta !== 'object') {
            contractsEl.textContent = Array.isArray(rows) && rows.length ? `${rows.length} strikes` : '—';
        } else {
            const selected = Number.parseInt(meta.contracts_selected, 10);
            const total = Number.parseInt(meta.contracts_total, 10);
            const selectedSafe = Number.isFinite(selected) ? selected : 0;
            const totalSafe = Number.isFinite(total) ? total : 0;
            contractsEl.textContent = `${selectedSafe}/${totalSafe}`;
        }
    }

    if (coverageEl) {
        if (!meta || typeof meta !== 'object') {
            coverageEl.textContent = '—';
        } else {
            const mark = Number.parseInt(meta.coverage_mark, 10);
            const selected = Number.parseInt(meta.contracts_selected, 10);
            const markSafe = Number.isFinite(mark) ? mark : 0;
            const selectedSafe = Number.isFinite(selected) && selected > 0 ? selected : 0;
            const ratio = selectedSafe > 0 ? `${Math.round((markSafe / selectedSafe) * 100)}%` : '0%';
            coverageEl.textContent = ratio;
        }
    }
}

function formatQuoteSourceBadge(optionQuote) {
    if (!optionQuote) {
        return '<span class="inline-flex items-center rounded px-1 py-0.5 text-[9px] font-semibold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">NO QUOTE</span>';
    }
    const source = String(optionQuote.mark_source || 'none').toLowerCase();
    const hasBidAsk = finitePositive(optionQuote.bid) !== null && finitePositive(optionQuote.ask) !== null;
    let label = 'NO QUOTE';
    let classes = 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300';

    if (source === 'live') {
        label = hasBidAsk ? 'LIVE B/A' : 'LIVE LAST';
        classes = 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300';
    } else if (source === 'model') {
        label = 'MODEL';
        classes = 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300';
    } else if (source === 'close') {
        label = 'CLOSE';
        classes = 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300';
    }

    return `<span class="inline-flex items-center rounded px-1 py-0.5 text-[9px] font-semibold ${classes}">${label}</span>`;
}

function buildChainStatusMessage(rows, meta) {
    const strikes = Array.isArray(rows) ? rows.length : 0;
    if (!meta || typeof meta !== 'object') {
        return `Chain loaded (${strikes} strikes). Select legs to build a strategy.`;
    }

    const selected = Number.parseInt(meta.contracts_selected, 10);
    const priced = Number.parseInt(meta.coverage_mark, 10);
    const bidAsk = Number.parseInt(meta.coverage_bidask, 10);

    const selectedSafe = Number.isFinite(selected) && selected > 0 ? selected : 0;
    const pricedSafe = Number.isFinite(priced) && priced >= 0 ? priced : 0;
    const bidAskSafe = Number.isFinite(bidAsk) && bidAsk >= 0 ? bidAsk : 0;

    let message = `Chain loaded: ${strikes} strikes | priced ${pricedSafe}/${selectedSafe} | live B/A ${bidAskSafe}`;
    if (meta.timed_out_contract_scan) {
        message += ' | partial contract scan';
    }
    if (meta.used_contract_cache) {
        message += ' | contract cache';
    }
    if (Number.parseInt(meta.snapshot_mark_recovered, 10) > 0) {
        message += ` | snapshot recovered ${meta.snapshot_mark_recovered}`;
    }
    return message;
}

async function loadOptionChain(symbol, expiry, strikeHalfWidth = 10) {
    setBuilderStatus(`Loading chain for ${symbol} ${formatBuilderExpiryLabel(expiry)}...`);
    try {
        const width = Math.max(2, Math.min(30, Number.parseInt(strikeHalfWidth, 10) || 10));
        const res = await fetch(`${API_BASE_URL}/option_chain?symbol=${encodeURIComponent(symbol)}&expiry=${encodeURIComponent(expiry)}&strike_half_width=${encodeURIComponent(width)}`);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Failed to load option chain.');
        }
        const data = await res.json();
        
        builderState.chain = data.rows || [];
        builderState.chainMeta = data.meta || null;
        builderState.underlyingPrice = data.undPrice || builderState.underlyingPrice;
        repriceBuilderLegsFromChain();
        updateUndSummary();
        updateChainDiagnostics(builderState.chainMeta, builderState.chain);
        renderChainTable(builderState.chain);
        renderBuilderLegs();
        maybeAutoFillBuilderLimitPrice();
        setBuilderStatus(buildChainStatusMessage(builderState.chain, builderState.chainMeta));
        refreshBuilderChart();
    } catch (e) {
        setBuilderStatus(`Error: ${e.message}`);
        console.error(e);
    }
}

function setBuilderStatus(msg) { if (s('builder-status')) s('builder-status').textContent = msg; }
function updateUndSummary() {
    const el = s('builder-und-summary');
    if (!el) return;
    if (!builderState.symbol) {
        el.textContent = '—';
        return;
    }
    const und = builderState.underlyingPrice;
    el.textContent = Number.isFinite(und) ? `${builderState.symbol} @ ${und.toFixed(2)}` : builderState.symbol;
}

function renderChainTable(rows) {
    const container = s('builder-chain-container');
    if (!container) return;
    if (!rows || rows.length === 0) {
        container.innerHTML = '<div class="p-4 text-muted text-sm text-center">No chain data to display.</div>';
        return;
    }

    const includeByFilter = (optionQuote) => {
        const quality = String(optionQuote?.quote_quality || '').toLowerCase();
        const source = String(optionQuote?.mark_source || '').toLowerCase();
        if (builderState.quoteFilter === 'LIVE') return quality === 'live' || source === 'live';
        if (builderState.quoteFilter === 'FALLBACK') return quality === 'fallback' || source === 'model' || source === 'close';
        return true;
    };

    const filteredRows = rows.filter((row) => includeByFilter(row?.call) || includeByFilter(row?.put));
    if (filteredRows.length === 0) {
        container.innerHTML = '<div class="p-4 text-muted text-sm text-center">No strikes match the selected quote filter.</div>';
        return;
    }

    const undPrice = builderState.underlyingPrice;
    let atmStrike = null;
    if (undPrice && filteredRows.length > 0) {
        atmStrike = filteredRows.reduce((prev, curr) => 
            (Math.abs(curr.strike - undPrice) < Math.abs(prev.strike - undPrice) ? curr : prev)
        ).strike;
    }

    const header = `<table><thead><tr>
        <th class="text-right">C Vol</th>
        <th class="text-right">C OI</th>
        <th class="text-right">C Ask</th>
        <th class="text-right">C Bid</th>
        <th class="text-center">C Side</th>
        <th class="text-right">C Δ</th>
        <th class="text-center">Strike</th>
        <th class="text-left">P Δ</th>
        <th class="text-center">P Side</th>
        <th class="text-left">P Bid</th>
        <th class="text-left">P Ask</th>
        <th class="text-left">P OI</th>
        <th class="text-left">P Vol</th>
        </tr></thead><tbody>`;
    
    let body = filteredRows.map(r => {
        const call = r.call || {}; 
        const put = r.put || {};
        const isAtm = r.strike === atmStrike;
        const callVol = formatCompactCount(call.volume);
        const callOi = formatCompactCount(call.open_interest ?? call.oi);
        const putVol = formatCompactCount(put.volume);
        const putOi = formatCompactCount(put.open_interest ?? put.oi);
        return `<tr class="${isAtm ? 'builder-ladder-atm' : ''}">
            <td class="text-right">${callVol}</td>
            <td class="text-right">${callOi}</td>
            <td class="text-right">${formatNum(call.ask)}</td>
            <td class="text-right">${formatNum(call.bid)}</td>
            <td class="text-center">
                <div class="flex items-center justify-center gap-2">
                    <button class="builder-side-buy px-1" onclick="addBuilderLeg('BUY','C',${r.strike})">B</button>
                    <button class="builder-side-sell px-1" onclick="addBuilderLeg('SELL','C',${r.strike})">S</button>
                </div>
                <div class="mt-0.5">${formatQuoteSourceBadge(call)}</div>
            </td>
            <td class="text-right font-semibold">
                ${formatNum(call.delta, 3)}
                <div class="text-[9px] text-muted mt-0.5">IV ${formatNum((call.iv || 0) * 100, 1)}%</div>
            </td>
            <td class="text-center font-semibold text-primary">${r.strike.toFixed(2)}</td>
            <td class="text-left font-semibold">
                ${formatNum(put.delta, 3)}
                <div class="text-[9px] text-muted mt-0.5">IV ${formatNum((put.iv || 0) * 100, 1)}%</div>
            </td>
            <td class="text-center">
                <div class="flex items-center justify-center gap-2">
                    <button class="builder-side-buy px-1" onclick="addBuilderLeg('BUY','P',${r.strike})">B</button>
                    <button class="builder-side-sell px-1" onclick="addBuilderLeg('SELL','P',${r.strike})">S</button>
                </div>
                <div class="mt-0.5">${formatQuoteSourceBadge(put)}</div>
            </td>
            <td class="text-left">${formatNum(put.bid)}</td>
            <td class="text-left">${formatNum(put.ask)}</td>
            <td class="text-left">${putOi}</td>
            <td class="text-left">${putVol}</td>
        </tr>`;
    }).join('');
    container.innerHTML = header + body + '</tbody></table>';
}

window.addBuilderLeg = function(side, right, strike) {
    if (!builderState.symbol || !builderState.selectedExpiry) {
        alert("Please load a symbol and expiry first.");
        return;
    }
    const row = builderState.chain.find(r => r.strike === strike) || {};
    const opt = (right === 'C') ? row.call : row.put;
    if (!opt || !opt.conId) {
        console.error("Could not find valid option leg for strike:", strike);
        return;
    }

    const price = getLegQuoteForPriceSource(opt);
    builderState.legs.push({
        side,
        qty: 1,
        right,
        strike,
        expiry: builderState.selectedExpiry,
        iv: parseNum(opt.iv, 0),
        price,
        conId: opt.conId,
        multiplier: 100
    });
    renderBuilderLegs();
    maybeAutoFillBuilderLimitPrice();
    refreshBuilderChart();
};

function renderBuilderLegs() {
    const container = s('builder-legs-container');
    if (!container) return;
    if (!builderState.legs.length) { 
        container.innerHTML = '<div class="p-4 text-muted text-sm text-center">No staged legs. Use the ladder B/S buttons.</div>'; 
        updateBuilderMetrics(null); 
        return; 
    }
    const fmtExpiry = (exp) => {
        const raw = String(exp || '');
        if (raw.length < 8) return raw || '--';
        return `${raw.slice(4, 6)}/${raw.slice(6, 8)}`;
    };
    const rows = builderState.legs.map((L, i) => `
        <div class="builder-legs-grid">
            <div class="font-semibold ${L.side === 'BUY' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}">${L.side} ${L.qty}</div>
            <div>${L.right}</div>
            <div>${Number(L.strike || 0).toFixed(2)}</div>
            <div>@ ${Number(L.price || 0).toFixed(2)}</div>
            <div>${fmtExpiry(L.expiry)}</div>
            <div><button onclick="removeBuilderLeg(${i})" class="text-muted hover:text-primary font-bold">✕</button></div>
        </div>`).join('');
    container.innerHTML = `<div class="builder-legs-grid builder-legs-grid-head"><div>Action</div><div>Type</div><div>Strike</div><div>Price</div><div>Exp</div><div></div></div><div>${rows}</div>`;
}

window.removeBuilderLeg = function(i) {
    builderState.legs.splice(i, 1);
    renderBuilderLegs();
    maybeAutoFillBuilderLimitPrice();
    refreshBuilderChart();
};

function updateBuilderMetrics(m) {
    const el = s('builder-metrics'); if (!el) return;
    if (!m) {
        el.innerHTML = [
            '<div class="builder-mini-stat"><div class="builder-mini-label">Net Cost</div><div class="builder-mini-value">—</div></div>',
            '<div class="builder-mini-stat"><div class="builder-mini-label">Max Profit</div><div class="builder-mini-value">—</div></div>',
            '<div class="builder-mini-stat"><div class="builder-mini-label">Max Loss</div><div class="builder-mini-value">—</div></div>',
            '<div class="builder-mini-stat"><div class="builder-mini-label">Breakevens</div><div class="builder-mini-value">—</div></div>',
        ].join('');
        return;
    }
    const breakevens = Array.isArray(m.breakevens) && m.breakevens.length ? m.breakevens.join(', ') : 'N/A';
    el.innerHTML = `
        <div class="builder-mini-stat"><div class="builder-mini-label">Net Cost</div><div class="builder-mini-value">${formatCurrency(m.netCost)}</div></div>
        <div class="builder-mini-stat"><div class="builder-mini-label">Max Profit</div><div class="builder-mini-value">${formatCurrency(m.maxProfit)}</div></div>
        <div class="builder-mini-stat"><div class="builder-mini-label">Max Loss</div><div class="builder-mini-value">${formatCurrency(m.maxLoss, true)}</div></div>
        <div class="builder-mini-stat"><div class="builder-mini-label">Breakevens</div><div class="builder-mini-value">${breakevens}</div></div>
    `;
}

// <-- MODIFIED: This function now calls the backend -->
async function refreshBuilderChart() {
    const S0 = builderState.underlyingPrice;
    if (!S0 || !builderState.legs.length) {
        drawBuilderChart(null); 
        updateBuilderMetrics(null);
        return;
    }

    // Find the max DTE to set the slider
    const today = new Date();
    const maxExpiry = new Date(Math.max(...builderState.legs.map(l => new Date(+l.expiry.slice(0,4), +l.expiry.slice(4,6)-1, +l.expiry.slice(6,8)))));
    const totalDays = Math.max(0, Math.round((maxExpiry - today) / 86400000));
    const dateSlider = s('builder-date-slider');
    dateSlider.max = String(totalDays);
    if (builderState.tPlusDays > totalDays) {
        builderState.tPlusDays = totalDays;
        dateSlider.value = String(totalDays);
        s('builder-date-label').textContent = `T+${builderState.tPlusDays}`;
    }

    const payload = {
        legs: builderState.legs,
        undPrice: S0,
        ivShift: builderState.ivShift,
        tPlusDays: builderState.tPlusDays,
        offset: builderState.offset,
        commission: builderState.commission
    };

    try {
        const res = await fetch(`${API_BASE_URL}/get_builder_profile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Failed to calculate profile.');
        }

        const data = await res.json();
        drawBuilderChart(data);
        updateBuilderMetrics(data.metrics);

    } catch (e) {
        console.error("Failed to refresh builder chart:", e);
        setBuilderStatus(`Error: ${e.message}`);
        drawBuilderChart(null);
        updateBuilderMetrics(null);
    }
}

function drawBuilderChart(payload) {
    const ctx = s('builder-chart-canvas')?.getContext('2d'); if (!ctx) return;
    if (builderChart) builderChart.destroy();
    if (!payload) { ctx.clearRect(0,0,ctx.canvas.width, ctx.canvas.height); return; }

    const cssVars = getComputedStyle(document.documentElement);
    const axisColor = cssVars.getPropertyValue('--text-muted').trim() || '#9ca3af';
    const legendColor = cssVars.getPropertyValue('--text-secondary').trim() || '#d1d5db';
    const gridColor = cssVars.getPropertyValue('--border-color').trim() || 'rgba(255,255,255,0.1)';
    
    builderChart = new Chart(ctx, { 
        type: 'line', 
        data: { 
            labels: payload.priceRange, 
            datasets: [ 
                { label: 'Expiration P&L', data: payload.expCurve, borderColor: '#f87171', borderWidth: 2, pointRadius: 0, borderDash: [5,5] }, 
                { label: `T+${builderState.tPlusDays} P&L`, data: payload.t0Curve, borderColor: '#4ade80', borderWidth: 3, pointRadius: 0, fill: { target:'origin', above:'rgba(74,222,128,0.1)', below:'rgba(248,113,113,0.1)' } } 
            ] 
        },
        options: { 
            responsive:true, 
            maintainAspectRatio:false, 
            scales: { 
                x:{ type:'linear', ticks:{color:axisColor, font:{size:10}}, grid:{color:gridColor}}, 
                y:{ ticks:{color:axisColor, font:{size:10}}, grid:{color:gridColor} } 
            }, 
            plugins:{ 
                legend:{ labels:{ color:legendColor} }, 
                annotation:{ annotations:{ zero:{ type:'line', yMin:0, yMax:0, borderColor:axisColor, borderWidth:1, borderDash:[2,2] } } } 
            } 
        } 
    });
}

// <-- REMOVED: All local calculation functions (computeBuilderCurves, findBreakevens, etc.) are no longer needed. -->
// <-- The file `blackscholes.js` is also no longer used by this script. -->

function clearBuilder() {
    const preservedAccounts = Array.isArray(builderState.accounts) ? [...builderState.accounts] : [];
    const preservedAccount = builderState.account;
    builderState = {
        symbol: '',
        underlyingPrice: null,
        selectedExpiry: '',
        expiries: [],
        chain: [],
        chainMeta: null,
        legs: [],
        priceSource: 'MID',
        quoteFilter: 'ALL',
        chainWindow: 10,
        offset: 0,
        commission: 0.65,
        tPlusDays: 0,
        ivShift: 0,
        account: preservedAccount,
        accounts: preservedAccounts
    };
    s('builder-symbol-input').value = '';
    s('builder-price-source').value = 'MID';
    s('builder-quote-filter').value = 'ALL';
    s('builder-chain-window').value = '10';
    s('builder-offset').value = '0';
    s('builder-commission').value = '0.65';
    populateBuilderAccountSelect(builderState.accounts, builderState.account);
    clearBuilderWorkingSet();
    s('builder-limit-price').dataset.autoMode = 'auto';
    setBuilderStatus('Cleared. Load a symbol to begin.');
}

async function placeBuilderOrder() {
    if (!Array.isArray(builderState.legs) || builderState.legs.length === 0) {
        alert('Add at least one leg before placing an order.');
        return;
    }

    const account = String(builderState.account || '').trim();
    if (!account) {
        alert('Select an account before placing an order.');
        return;
    }

    const limitPriceRaw = parseNum(s('builder-limit-price').value, NaN);
    if (!Number.isFinite(limitPriceRaw)) {
        alert('Enter a valid net limit price.');
        return;
    }

    const payloadLegs = builderState.legs.map((leg) => {
        const qty = Math.max(1, Math.abs(parseNum(leg.qty, 1)));
        const signedQty = leg.side === 'BUY' ? -qty : qty;
        return { conId: leg.conId, qty: signedQty };
    });

    if (payloadLegs.some((leg) => !Number.isFinite(leg.conId) || !Number.isFinite(leg.qty) || leg.qty === 0)) {
        alert('Some legs are missing conId/qty. Reload the chain and re-add those legs.');
        return;
    }

    const placeButtons = ['builder-place-btn', 'builder-place-btn-mobile']
        .map((id) => s(id))
        .filter(Boolean);
    const previousTexts = placeButtons.map((btn) => btn.textContent);
    placeButtons.forEach((btn) => {
        btn.disabled = true;
        btn.textContent = 'Sending...';
    });

    try {
        const response = await fetch(`${API_BASE_URL}/place_order`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                legs: payloadLegs,
                orderType: 'LMT',
                limitPrice: limitPriceRaw,
                symbol: builderState.symbol,
                account,
                tif: 'DAY'
            })
        });

        if (!response.ok) {
            let message = 'Failed to place builder order.';
            try {
                const err = await response.json();
                message = err.error || message;
            } catch (_) {
                // ignore parse errors
            }
            throw new Error(message);
        }

        const payload = await response.json();
        setBuilderStatus(payload.message || 'Order sent to TWS. Check Activity Monitor to transmit.');
        alert(payload.message || 'Order sent to TWS. Check Activity Monitor to transmit.');
    } catch (error) {
        setBuilderStatus(`Error: ${error.message}`);
        alert(`Order failed: ${error.message}`);
    } finally {
        placeButtons.forEach((btn, idx) => {
            btn.disabled = false;
            btn.textContent = previousTexts[idx] || 'Place';
        });
    }
}

// Make sure it's initialized after the main client script runs
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBuilderUI);
} else {
    initBuilderUI();
}
