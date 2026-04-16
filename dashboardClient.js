let currentRiskChartPriceRange = null;
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// ========================================================================================
// --- GLOBAL VARIABLES & CONFIG ---
// ========================================================================================
const API_BASE_URL = "http://127.0.0.1:5001";
let portfolioData = {}, customCombos = [], expandedCombos = new Set();
let riskChart = null, threeApp = null, updateInterval = null;
let underlyingPrices = {};
let comboSort = { column: 'created', direction: 'desc' };
let tempComboLegs = [];
let legToClose = { comboIndex: null, legIndex: null };
let legToEdit = { comboIndex: null, legIndex: null };
let addLegsMode = { enabled: false, comboIndex: null, symbol: '' };
let selectedCombos = new Set();
let currentRiskProfileData = null;
let currentRiskProfileLegs = null;
let currentRiskTableData = null;
let currentRiskAccountContext = null;
let riskStripCharts = {};
let currentRiskStripSeries = {};
let currentRiskCrosshairPrice = null;
let currentRiskCrosshairIndex = -1;
let riskActiveView = 'graph';
let lastRiskSourceTab = 'combos';
let riskIvEnabled = true;
let riskTimeEnabled = true;
let riskAdjustmentEnabled = false;
let sgpvChart = null;
let currentSgpvData = null;
let chartPluginsRegistered = false;
let positionToClose = null;
let comboToClose = null;
let comboRenderCacheKey = '';
let selectedAccountFilter = 'All';
let currentPortfolioRiskDigest = null;
let riskTableUiState = {
    metric: 'pnl',
    columns: 20,
    rangePct: 5,
    strikeStepsEachSide: 10,
};
let sgpvUiState = {
    columns: 6,
    rangePct: 55,
    strikeStepsEachSide: 11,
    netLiq: null,
};
let sgpvNetLiqManualOverride = false;
let currentRiskChainContext = null;

// ========================================================================================
// --- HELPER & UTILITY FUNCTIONS ---
// ========================================================================================
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VALID_COMBO_LEG_STATUSES = new Set(['open', 'closed']);
const RISK_STRIP_DEFS = [
    { key: 'pnl', source: 'pnl', id: 'risk-strip-pnl', valueId: 'risk-strip-value-pnl', color: '#5ac8ff' },
    { key: 'delta', source: 'delta', id: 'risk-strip-delta', valueId: 'risk-strip-value-delta', color: '#37d1a8' },
    { key: 'theta', source: 'theta', id: 'risk-strip-theta', valueId: 'risk-strip-value-theta', color: '#f59e0b' },
    { key: 'wtvega', source: 'vega', id: 'risk-strip-wtvega', valueId: 'risk-strip-value-wtvega', color: '#d946ef' },
];
const RISK_TABLE_METRIC_DEFS = {
    pnl: { label: 'P&L', currency: true, digits: 0 },
    pnl_pct: { label: 'P&L %', suffix: '%', digits: 1 },
    delta: { label: 'Delta', digits: 2 },
    gamma: { label: 'Gamma', digits: 3 },
    theta: { label: 'Theta', digits: 2 },
    vega: { label: 'Vega', digits: 2 },
};

function parseNumber(value, defaultValue = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : defaultValue;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function getRiskLegContract(leg) {
    if (leg?.tws_data?.contract) return leg.tws_data.contract;
    if (leg?.contract) return leg.contract;
    if (leg?.conId != null && portfolioData[leg.conId]?.contract) return portfolioData[leg.conId].contract;
    return leg || {};
}

function deriveRiskChainContext(legs) {
    const optionContracts = [];
    (legs || []).forEach((leg) => {
        const contract = getRiskLegContract(leg);
        const secType = String(contract?.secType || leg?.secType || 'OPT').toUpperCase();
        if (secType !== 'OPT') return;
        const expiry = String(contract?.expiry || leg?.expiry || '');
        if (!/^\d{8}$/.test(expiry)) return;
        const symbol = String(contract?.symbol || leg?.symbol || '').toUpperCase();
        if (!symbol) return;
        optionContracts.push({ symbol, expiry });
    });

    if (!optionContracts.length) return null;
    const symbolCounts = new Map();
    optionContracts.forEach(({ symbol }) => symbolCounts.set(symbol, (symbolCounts.get(symbol) || 0) + 1));
    const symbol = [...symbolCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || optionContracts[0].symbol;
    const expiries = optionContracts
        .filter((row) => row.symbol === symbol)
        .map((row) => row.expiry)
        .sort();
    const expiry = expiries[0] || optionContracts[0].expiry;
    return { symbol, expiry };
}

function renderRiskChainStatus(message = '', isError = false) {
    const statusEl = document.getElementById('risk-chain-status');
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.toggle('text-red-500', !!isError);
}

function renderRiskChainPlaceholder(message) {
    const body = document.getElementById('risk-chain-table-body');
    if (!body) return;
    body.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-2">${escapeHtml(message)}</td></tr>`;
}

function renderRiskChainContextUi(ctx) {
    const contextEl = document.getElementById('risk-chain-context');
    const dteChip = document.getElementById('risk-chain-dte-chip');
    if (contextEl) {
        contextEl.textContent = ctx
            ? `${ctx.symbol} • ${ctx.expiry.slice(0, 4)}-${ctx.expiry.slice(4, 6)}-${ctx.expiry.slice(6, 8)}`
            : 'Select a profile to load chain.';
    }
    if (dteChip) {
        if (!ctx) {
            dteChip.textContent = '-- DTE';
            return;
        }
        const dteInfo = calculateDTE(ctx.expiry);
        const days = Number.isFinite(dteInfo.days) ? dteInfo.days : '--';
        dteChip.textContent = `${days} DTE`;
    }
}

function renderRiskOptionChainRows(rows, undPrice) {
    const body = document.getElementById('risk-chain-table-body');
    if (!body) return;
    if (!Array.isArray(rows) || !rows.length) {
        renderRiskChainPlaceholder('No chain rows returned.');
        return;
    }
    const sorted = [...rows].sort((a, b) => parseNumber(a?.strike, 0) - parseNumber(b?.strike, 0));
    const atmIdx = sorted.reduce((bestIdx, row, idx) => {
        const strike = parseNumber(row?.strike, NaN);
        if (!Number.isFinite(strike) || !Number.isFinite(undPrice)) return bestIdx;
        if (bestIdx < 0) return idx;
        const bestStrike = parseNumber(sorted[bestIdx]?.strike, NaN);
        return Math.abs(strike - undPrice) < Math.abs(bestStrike - undPrice) ? idx : bestIdx;
    }, -1);
    const tableRows = sorted.map((row, idx) => {
        const callDelta = parseNumber(row?.call?.delta, NaN);
        const callMid = parseNumber(row?.call?.mid, NaN);
        const putMid = parseNumber(row?.put?.mid, NaN);
        const putDelta = parseNumber(row?.put?.delta, NaN);
        const strike = parseNumber(row?.strike, NaN);
        return `
            <tr class="${idx === atmIdx ? 'risk-chain-row-atm' : ''}">
                <td class="risk-chain-cell-calls">${Number.isFinite(callDelta) ? `${callDelta >= 0 ? '+' : ''}${callDelta.toFixed(2)}` : '—'}</td>
                <td class="risk-chain-cell-calls">${Number.isFinite(callMid) ? formatNumber(callMid, 2) : '—'}</td>
                <td class="text-center text-secondary font-semibold">${Number.isFinite(strike) ? formatNumber(strike, 2) : '—'}</td>
                <td class="text-right risk-chain-cell-puts">${Number.isFinite(putMid) ? formatNumber(putMid, 2) : '—'}</td>
                <td class="text-right risk-chain-cell-puts">${Number.isFinite(putDelta) ? `${putDelta >= 0 ? '+' : ''}${putDelta.toFixed(2)}` : '—'}</td>
            </tr>
        `;
    }).join('');
    body.innerHTML = tableRows;
}

async function loadRiskOptionChain(legs) {
    const context = deriveRiskChainContext(legs);
    currentRiskChainContext = context;
    renderRiskChainContextUi(context);
    if (!context) {
        renderRiskChainPlaceholder('No option contracts in selection.');
        renderRiskChainStatus('');
        return;
    }

    const windowEl = document.getElementById('risk-chain-window');
    const halfWidth = Math.max(2, Math.min(12, parseInt(windowEl?.value || '5', 10)));
    renderRiskChainPlaceholder('Loading option chain...');
    renderRiskChainStatus('Fetching live chain...');

    try {
        const url = `${API_BASE_URL}/option_chain?symbol=${encodeURIComponent(context.symbol)}&expiry=${encodeURIComponent(context.expiry)}&strike_half_width=${halfWidth}`;
        const res = await fetch(url);
        if (!res.ok) {
            let message = 'Unable to load option chain.';
            try {
                const err = await res.json();
                message = err.error || message;
            } catch (e) {}
            throw new Error(message);
        }
        const payload = await res.json();
        renderRiskOptionChainRows(payload.rows || [], parseNumber(payload.undPrice, NaN));
        const coverageAny = parseNumber(payload?.meta?.coverage_any, 0);
        const coverageSelected = parseNumber(payload?.meta?.contracts_selected, 0);
        renderRiskChainStatus(
            `Live coverage ${coverageAny}/${coverageSelected} • Spot ${Number.isFinite(parseNumber(payload?.undPrice, NaN)) ? `$${formatNumber(parseNumber(payload.undPrice, 0), 2)}` : 'N/A'}`
        );
    } catch (error) {
        renderRiskChainPlaceholder(error.message || 'Unable to load option chain.');
        renderRiskChainStatus(error.message || 'Unable to load option chain.', true);
    }
}

function ensureChartPluginsRegistered() {
    if (chartPluginsRegistered || typeof Chart === 'undefined' || typeof Chart.register !== 'function') return;
    const plugins = [
        window['chartjs-plugin-zoom'],
        window.ChartZoom,
        window.zoomPlugin,
        window['chartjs-plugin-annotation'],
        window.ChartAnnotation
    ];
    plugins.forEach((plugin) => {
        if (!plugin) return;
        try { Chart.register(plugin); } catch (error) {}
    });
    chartPluginsRegistered = true;
}

function enforceRiskModalLayout() {
    const modalContent = document.getElementById('risk-modal-content');
    if (modalContent) {
        modalContent.style.width = '100%';
        modalContent.style.maxHeight = 'none';
        modalContent.style.overflow = 'visible';
    }
    const panelWidth = document.getElementById('risk-panel')?.clientWidth || window.innerWidth;
    const compact = panelWidth < 1024;
    const vhRatio = compact ? 0.48 : 0.56;
    const minHeight = compact ? 320 : 380;
    const maxHeight = compact ? 560 : 730;
    const targetHeightPx = Math.max(minHeight, Math.min(Math.round(window.innerHeight * vhRatio), maxHeight));
    document.querySelectorAll('#risk-panel .risk-chart-shell').forEach((chartShell) => {
        chartShell.style.height = `${targetHeightPx}px`;
    });
}

function getLegMultiplier(twsLeg) {
    return parseNumber(twsLeg?.contract?.multiplier, 100) || 100;
}

function normalizeComboLeg(rawLeg) {
    if (!rawLeg || typeof rawLeg !== 'object') return null;
    const conId = Number(rawLeg.conId);
    const qty = parseNumber(rawLeg.qty, NaN);
    if (!Number.isInteger(conId) || Number.isNaN(qty)) return null;
    const status = VALID_COMBO_LEG_STATUSES.has(String(rawLeg.status || '').toLowerCase()) ? String(rawLeg.status).toLowerCase() : 'open';
    const costBasis = rawLeg.costBasis == null ? null : parseNumber(rawLeg.costBasis, null);
    const realizedPnl = parseNumber(rawLeg.realizedPnl, 0);
    const normalized = { conId, qty, status, costBasis, realizedPnl };
    if (rawLeg.closingPrice != null) normalized.closingPrice = parseNumber(rawLeg.closingPrice, 0);
    return normalized;
}

function normalizeCombo(rawCombo, index) {
    if (!rawCombo || typeof rawCombo !== 'object') return null;
    const name = String(rawCombo.name || `Combo ${index + 1}`).trim() || `Combo ${index + 1}`;
    const group = String(rawCombo.group || 'Default').trim() || 'Default';
    const createdAt = typeof rawCombo.createdAt === 'string' && rawCombo.createdAt.trim()
        ? rawCombo.createdAt
        : new Date().toISOString();

    let legs = [];
    if (Array.isArray(rawCombo.legs)) {
        legs = rawCombo.legs.map(normalizeComboLeg).filter(Boolean);
    } else if (Array.isArray(rawCombo.legConIds)) {
        legs = rawCombo.legConIds
            .filter((conId) => Number.isInteger(conId))
            .map((conId) => ({ conId, qty: 0, status: 'open', costBasis: null, realizedPnl: 0 }));
    }
    return { name, group, createdAt, legs };
}

function normalizeCombos(rawCombos) {
    if (!Array.isArray(rawCombos)) return [];
    return rawCombos.map(normalizeCombo).filter(Boolean);
}

function getComboLegCostBasis(comboLeg, twsLeg) {
    if (comboLeg.costBasis != null) return parseNumber(comboLeg.costBasis, 0);
    if (!twsLeg) return 0;
    const twsPosition = parseNumber(twsLeg.position, 0);
    return twsPosition !== 0 ? parseNumber(twsLeg.costBasis, 0) * (parseNumber(comboLeg.qty, 0) / twsPosition) : 0;
}

function getComboLegRatio(comboLeg, twsLeg) {
    const twsPosition = parseNumber(twsLeg?.position, 0);
    return twsPosition !== 0 ? parseNumber(comboLeg.qty, 0) / twsPosition : 0;
}

function computeComboMetrics(combo) {
    const metrics = { dailyPnl: 0, totalReturn: 0, delta: 0, theta: 0, vega: 0, gamma: 0, costBasis: 0, live: true, earliestExpiry: '99999999' };
    (combo.legs || []).forEach((comboLeg) => {
        const twsLeg = portfolioData[comboLeg.conId];
        const legCostBasis = getComboLegCostBasis(comboLeg, twsLeg);
        metrics.costBasis += legCostBasis;

        if (comboLeg.status === 'closed') {
            metrics.totalReturn += parseNumber(comboLeg.realizedPnl, 0);
            return;
        }

        if (!twsLeg) {
            metrics.live = false;
            return;
        }
        if (!twsLeg.status || !(twsLeg.status.startsWith('Live') || twsLeg.status === 'Snapshot')) {
            metrics.live = false;
        }
        if (twsLeg.contract?.expiry && twsLeg.contract.expiry < metrics.earliestExpiry) {
            metrics.earliestExpiry = twsLeg.contract.expiry;
        }

        const ratio = getComboLegRatio(comboLeg, twsLeg);
        const multiplier = getLegMultiplier(twsLeg);
        metrics.totalReturn += (parseNumber(twsLeg.marketValue, 0) * ratio) - legCostBasis;
        metrics.dailyPnl += parseNumber(twsLeg.pnl?.daily, 0) * ratio;
        metrics.delta += parseNumber(twsLeg.greeks?.delta, 0) * parseNumber(comboLeg.qty, 0) * multiplier;
        metrics.theta += parseNumber(twsLeg.greeks?.theta, 0) * parseNumber(comboLeg.qty, 0) * multiplier;
        metrics.vega += parseNumber(twsLeg.greeks?.vega, 0) * parseNumber(comboLeg.qty, 0) * multiplier;
        metrics.gamma += parseNumber(twsLeg.greeks?.gamma, 0) * parseNumber(comboLeg.qty, 0) * multiplier;
    });
    return metrics;
}

function buildComboRenderCacheKey() {
    const pieces = [comboSort.column, comboSort.direction, document.getElementById('group-filter-select')?.value || 'All', document.getElementById('combo-filter-input')?.value || '', String(expandedCombos.size)];
    customCombos.forEach((combo, comboIndex) => {
        pieces.push(combo.name, combo.group || '', combo.createdAt || '', String(combo.legs?.length || 0), String(selectedCombos.has(comboIndex)));
        (combo.legs || []).forEach((leg) => {
            const tws = portfolioData[leg.conId];
            pieces.push(
                String(leg.conId),
                String(leg.qty),
                String(leg.status || 'open'),
                String(leg.costBasis ?? ''),
                String(leg.realizedPnl ?? 0),
                tws ? `${tws.position}|${tws.marketValue}|${tws.pnl?.daily}|${tws.greeks?.delta}|${tws.greeks?.theta}|${tws.greeks?.vega}|${tws.greeks?.gamma}|${tws.status}` : 'missing'
            );
        });
    });
    return pieces.join('~');
}

function updateCombosView(force = false) {
    const nextKey = buildComboRenderCacheKey();
    if (!force && nextKey === comboRenderCacheKey) return;
    comboRenderCacheKey = nextKey;
    renderCustomCombos();
}

function getSortedAccountsFromPortfolio() {
    const accounts = new Set();
    Object.values(portfolioData).forEach((leg) => {
        const account = String(leg?.account || '').trim();
        if (account) accounts.add(account);
    });
    return Array.from(accounts).sort((a, b) => a.localeCompare(b));
}

function syncAccountFilterOptions() {
    const accountSelect = document.getElementById('filter-account');
    if (!accountSelect) return;

    const accounts = getSortedAccountsFromPortfolio();
    const currentSelection = selectedAccountFilter || accountSelect.value || 'All';

    accountSelect.innerHTML = '<option value="All">All Accounts</option>';
    accounts.forEach((account) => {
        const option = document.createElement('option');
        option.value = account;
        option.textContent = account;
        accountSelect.appendChild(option);
    });

    selectedAccountFilter = (currentSelection === 'All' || accounts.includes(currentSelection)) ? currentSelection : 'All';
    accountSelect.value = selectedAccountFilter;
}

function formatDate(yyyymmdd) {
    if (!yyyymmdd || String(yyyymmdd).length !== 8) return yyyymmdd;
    const year = parseInt(yyyymmdd.substring(0, 4), 10);
    const month = parseInt(yyyymmdd.substring(4, 6), 10) - 1;
    const day = parseInt(yyyymmdd.substring(6, 8), 10);
    return `${day}-${MONTH_NAMES[month]}-${String(year).slice(2)}`;
}

async function loadCombosFromServer() {
    try {
        const res = await fetch(`${API_BASE_URL}/get_combos`);
        if (!res.ok) {
            console.error("Could not load combos, server responded with error.");
            customCombos = [];
            return;
        }
        customCombos = normalizeCombos(await res.json());
        comboRenderCacheKey = '';
    } catch (e) {
        console.error("Could not load combos from server:", e);
        customCombos = [];
    }
}
async function saveCombosToServer() {
    try {
        customCombos = normalizeCombos(customCombos);
        const response = await fetch(`${API_BASE_URL}/save_combos`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(customCombos)
        });
        if (!response.ok) {
            let message = 'Could not save combos.';
            try {
                const payload = await response.json();
                message = payload.error || message;
            } catch (e) {}
            throw new Error(message);
        }
        comboRenderCacheKey = '';
    } catch (e) {
        console.error("Could not save combos to server:", e);
        alert(`Failed to save combos: ${e.message}`);
    }
}

function calculateDTE(expiryString) {
    if (!expiryString || String(expiryString).length !== 8) return { days: 'N/A', date: '' };
    const year = parseInt(String(expiryString).substring(0, 4), 10);
    const month = parseInt(String(expiryString).substring(4, 6), 10) - 1;
    const day = parseInt(String(expiryString).substring(6, 8), 10);
    const expiryDate = new Date(year, month, day);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    expiryDate.setHours(0, 0, 0, 0);
    // Add 1 hour to expiry to ensure same-day expiry shows 0 DTE, not -1
    const diffTime = expiryDate.getTime() + 3600000 - today.getTime();
    const diffDays = Math.max(0, Math.floor(diffTime / (1000 * 60 * 60 * 24))); // Use floor and max(0)
    return {
        days: diffDays,
        date: `${day}-${MONTH_NAMES[month]}-${String(year).slice(2)}`
    };
}


function formatNumber(v,d=2) { return (typeof v === 'number' && !isNaN(v)) ? v.toFixed(d) : 'N/A';}

// Use standard text color for greeks, rely on CSS variables for light/dark
function coloredGreek(val) {
    if (typeof val !== 'number' || isNaN(val)) return `<span class="text-muted">---</span>`;
    // Removed specific light/dark check, using CSS vars now
    return `<span class="text-secondary">${formatNumber(val, 4)}</span>`;
}


function getStatusSpan(s) { const c = { 'Live': 'bg-green-500', 'Live (EOD)': 'bg-blue-500', 'Error': 'bg-red-500', 'Loading...': 'bg-yellow-500', 'Queued': 'bg-gray-500', 'Snapshot': 'bg-purple-500'}; return `<span class="px-2 py-0.5 text-[10px] md:text-xs font-semibold rounded-full ${c[s] || 'bg-gray-600'} text-white">${s}</span>`; }
function hideModal(m) {
    if(!m) return;
    m.classList.add('hidden');
    if (m.id === 'risk-panel') {
        if (riskChart) { riskChart.destroy(); riskChart = null; }
        if (sgpvChart) { sgpvChart.destroy(); sgpvChart = null; }
        destroyRiskStripCharts();
        currentRiskTableData = null;
        currentSgpvData = null;
        currentRiskAccountContext = null;
        sgpvNetLiqManualOverride = false;
        currentRiskChainContext = null;
        renderRiskChainContextUi(null);
        renderRiskChainPlaceholder('No chain loaded.');
        renderRiskChainStatus('');
        renderSgpvContextNote();
        clearRiskOverlayPanels();
    }
    if (m.id === 'd3-modal' && threeApp) { threeApp.stop(); threeApp = null; }
}

// formatCurrency now relies on CSS variables for colors defined in HTML <style>
function formatCurrency(v, s=false) {
    if (v === "Unlimited") {
        return `<span class="font-semibold text-primary">Unlimited</span>`;
    }
    if (typeof v !== 'number' || isNaN(v)) return '<span class="text-muted">N/A</span>';

    const colorClass = v >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400';
    const sign = v >= 0 && s ? '+' : '';
    return `<span class="${colorClass}">${sign}${v.toLocaleString('en-US',{style:'currency',currency:'USD'})}</span>`;
}

// formatPnlWithPercent relies on formatCurrency and text-muted CSS var
function formatPnlWithPercent(pnl, costBasis) {
    if (typeof pnl !== 'number' || isNaN(pnl)) return '<span class="text-muted">N/A</span>';
    const pnlString = formatCurrency(pnl, true); // sign included by formatCurrency
    const pct = (costBasis && Math.abs(costBasis) > 1e-6) ? (pnl / Math.abs(costBasis)) * 100 : 0; // Avoid division by zero
    const pctString = `<span class="text-xs text-muted"> (${pct.toFixed(1)}%)</span>`;
    return `${pnlString}${pctString}`;
}

function formatCurrencyText(value, digits = 0) {
    const parsed = parseNumber(value, NaN);
    if (!Number.isFinite(parsed)) return 'N/A';
    return parsed.toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: digits,
    });
}

function renderPortfolioRiskDigestLoading(message = 'Loading portfolio risk digest...') {
    const container = document.getElementById('portfolio-risk-digest');
    if (!container) return;
    container.innerHTML = `<div class="text-sm text-muted">${message}</div>`;
}

function renderPortfolioRiskDigest(data) {
    const container = document.getElementById('portfolio-risk-digest');
    if (!container) return;
    if (!data || !data.sgpv || !data.net_liq) {
        container.innerHTML = '<div class="text-sm text-muted">No digest data available.</div>';
        return;
    }

    const selected = data.selected_account || 'All';
    const ratio = parseNumber(data.sgpv.ratio, 0);
    const warningRatio = parseNumber(data.sgpv.open_restriction_ratio, 30);
    const liqRatio = parseNumber(data.sgpv.liquidation_ratio, 50);
    const ratioColor = ratio >= liqRatio ? 'text-red-400' : (ratio >= warningRatio ? 'text-amber-300' : 'text-emerald-300');
    const source = data.net_liq.source || 'estimate';
    const twsAge = parseNumber(data?.tws_account_summary?.age_sec, NaN);
    const twsAgeText = Number.isFinite(twsAge) ? `${twsAge.toFixed(1)}s` : 'N/A';
    const expiringRows = Array.isArray(data.expiring_soon) ? data.expiring_soon : [];

    let alertsHtml = '';
    if (expiringRows.length === 0) {
        alertsHtml = '<div class="text-xs text-muted">No option expiries within 7 days.</div>';
    } else {
        alertsHtml = expiringRows.slice(0, 5).map((row) => `
            <div class="risk-digest-alert-row text-xs">
                <div class="font-mono ${row.dte <= 1 ? 'text-red-300' : 'text-amber-200'}">T+${row.dte}</div>
                <div class="truncate text-secondary">${row.description || row.symbol || 'Option'}</div>
                <div class="text-right text-muted">${row.account || ''}</div>
            </div>
        `).join('');
    }

    container.innerHTML = `
        <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div class="text-sm font-semibold text-primary">Portfolio Risk Digest (${selected})</div>
            <div class="text-[11px] text-muted">NetLiq source: ${source} | TWS age: ${twsAgeText}</div>
        </div>
        <div class="grid grid-cols-2 lg:grid-cols-5 gap-2 mb-2">
            <div class="risk-digest-pill">
                <div class="text-[11px] text-muted">SGPV</div>
                <div class="text-sm font-semibold text-primary">${formatCurrencyText(data.sgpv.value, 0)}</div>
            </div>
            <div class="risk-digest-pill">
                <div class="text-[11px] text-muted">NetLiq</div>
                <div class="text-sm font-semibold text-primary">${formatCurrencyText(data.net_liq.value, 0)}</div>
            </div>
            <div class="risk-digest-pill">
                <div class="text-[11px] text-muted">SGPV / NetLiq</div>
                <div class="text-sm font-semibold ${ratioColor}">${formatNumber(ratio, 2)}x</div>
            </div>
            <div class="risk-digest-pill">
                <div class="text-[11px] text-muted">Open Restriction</div>
                <div class="text-sm font-semibold text-amber-300">${formatCurrencyText(data.sgpv.open_restriction_value, 0)}</div>
            </div>
            <div class="risk-digest-pill">
                <div class="text-[11px] text-muted">Liquidation</div>
                <div class="text-sm font-semibold text-red-300">${formatCurrencyText(data.sgpv.liquidation_value, 0)}</div>
            </div>
        </div>
        <div class="risk-digest-pill">
            <div class="text-[11px] text-muted mb-1">Expiring Soon (7D)</div>
            ${alertsHtml}
        </div>
    `;
}

async function loadPortfolioRiskDigest() {
    const account = encodeURIComponent(selectedAccountFilter || 'All');
    try {
        const response = await fetch(`${API_BASE_URL}/get_portfolio_risk_digest?account=${account}`);
        if (!response.ok) {
            let errorText = 'Failed to load risk digest.';
            try { errorText = (await response.json()).error || errorText; } catch (e) {}
            throw new Error(errorText);
        }
        currentPortfolioRiskDigest = await response.json();
        renderPortfolioRiskDigest(currentPortfolioRiskDigest);
    } catch (error) {
        currentPortfolioRiskDigest = null;
        renderPortfolioRiskDigestLoading(error.message);
    }
}


function setOverlayMessage(container, message) { let overlay = container.querySelector('.three-overlay'); if (!overlay) { overlay = document.createElement('div'); overlay.className = 'three-overlay'; overlay.style.cssText = 'position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color: var(--text-muted); pointer-events:none; z-index: 10;'; container.style.position = 'relative'; container.appendChild(overlay); } overlay.innerHTML = message || ''; overlay.style.display = message ? 'flex' : 'none'; }

function activateTab(tabName) {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanels = document.querySelectorAll('.tab-panel');
    tabButtons.forEach((btn) => {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tabName);
    });
    tabPanels.forEach((panel) => {
        panel.classList.toggle('hidden', panel.id !== `${tabName}-panel`);
    });
    const riskPanel = document.getElementById('risk-panel');
    if (
        riskPanel &&
        !riskPanel.classList.contains('hidden') &&
        tabName !== lastRiskSourceTab
    ) {
        hideModal(riskPanel);
    }
}

function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    tabButtons.forEach(button => {
        button.addEventListener('click', (e) => {
            if (addLegsMode.enabled && e.target.getAttribute('data-tab') !== 'portfolio') {
                alert('Please finish or cancel adding legs before switching tabs.');
                return;
            }
            const tabName = button.getAttribute('data-tab');
            activateTab(tabName);
        });
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    console.log("DOM Loaded. Initializing..."); // Add log
    ensureChartPluginsRegistered();
    enforceRiskModalLayout();
    window.addEventListener('resize', enforceRiskModalLayout);
    initTabs();
    applyInitialTheme(); // Apply theme on load
    await loadCombosFromServer();
    bindEventListeners(); // Bind listeners after DOM is ready
    fetchInitialData(); // Fetch data after setup
});

function bindEventListeners() {
    console.log("Binding event listeners..."); // Add log
    const el = (id, event, handler) => {
        const element = document.getElementById(id);
        if (element) {
             element.addEventListener(event, handler);
             // console.log(`Listener added for ${id} - ${event}`); // Add detailed log
        } else {
            console.warn(`Element with ID ${id} not found for event listener.`);
        }
    };

    // Corrected the create-combo-btn listener logic
    el('create-combo-btn', 'click', () => {
        const nameInput = document.getElementById('combo-name-input');
        const selectedCheckboxes = document.querySelectorAll('#legs-table-body tr:not([style*="display: none"]) .leg-checkbox:checked');

        if (!nameInput || nameInput.value.trim() === '') {
             alert("Please enter a name for the new combo.");
             return;
        }
        if (selectedCheckboxes.length === 0) {
            alert("Please select at least one leg from the Portfolio table to create a new combo.");
            return;
        }
        prepareComboEditor(selectedCheckboxes);
    });

    el('select-all-checkbox', 'change', toggleSelectAll); // This ID exists
    el('refresh-btn', 'click', manualRefreshPositions); // This ID exists
    el('save-snapshot-btn', 'click', savePortfolioSnapshot); // This ID exists
    el('filter-account', 'change', (event) => {
        selectedAccountFilter = event.target.value || 'All';
        filterLegsTable();
        loadPortfolioRiskDigest();
    });
    el('filter-ticker', 'input', filterLegsTable); // This ID exists
    el('filter-expiry', 'input', filterLegsTable); // This ID exists
    el('filter-strike', 'input', filterLegsTable); // This ID exists
    el('combo-filter-input', 'input', () => updateCombosView(true)); // This ID exists
    el('group-filter-select', 'change', () => updateCombosView(true)); // This ID exists
    el('modal-close-btn', 'click', () => {
        if (lastRiskSourceTab) activateTab(lastRiskSourceTab);
        hideModal(document.getElementById('risk-panel'));
    });
    el('risk-view-graph-btn', 'click', () => setRiskModalView('graph'));
    el('risk-view-table-btn', 'click', () => setRiskModalView('table'));
    el('risk-view-sgpv-btn', 'click', () => setRiskModalView('sgpv'));
    el('risk-chain-window', 'change', () => {
        if (currentRiskProfileLegs && currentRiskProfileLegs.length) {
            loadRiskOptionChain(currentRiskProfileLegs);
        }
    });
    el('risk-table-metric', 'change', () => {
        getRiskTableSettingsFromControls();
        renderRiskTable();
    });
    el('risk-table-columns', 'change', () => {
        getRiskTableSettingsFromControls();
        if (currentRiskProfileLegs && currentRiskProfileData?.metrics) loadRiskTableData(currentRiskProfileLegs, currentRiskProfileData.metrics);
    });
    el('risk-table-range', 'change', () => {
        getRiskTableSettingsFromControls();
        if (currentRiskProfileLegs && currentRiskProfileData?.metrics) loadRiskTableData(currentRiskProfileLegs, currentRiskProfileData.metrics);
    });
    el('risk-table-rows', 'change', () => {
        getRiskTableSettingsFromControls();
        if (currentRiskProfileLegs && currentRiskProfileData?.metrics) loadRiskTableData(currentRiskProfileLegs, currentRiskProfileData.metrics);
    });
    el('risk-table-reset-btn', 'click', () => {
        riskTableUiState = { metric: 'pnl', columns: 20, rangePct: 5, strikeStepsEachSide: 10 };
        syncRiskTableControls();
        if (currentRiskProfileLegs && currentRiskProfileData?.metrics) loadRiskTableData(currentRiskProfileLegs, currentRiskProfileData.metrics);
    });
    el('sgpv-refresh-btn', 'click', () => {
        getSgpvSettingsFromControls();
        if (currentRiskProfileLegs && currentRiskProfileData?.metrics) loadSgpvData(currentRiskProfileLegs, currentRiskProfileData.metrics);
    });
    el('sgpv-account-select', 'change', async () => {
        if (!currentRiskProfileLegs || !currentRiskProfileData?.metrics) return;
        sgpvNetLiqManualOverride = false;
        await loadAccountRiskContext(currentRiskProfileLegs);
        await loadSgpvData(currentRiskProfileLegs, currentRiskProfileData.metrics);
    });
    el('sgpv-netliq-input', 'input', () => {
        sgpvNetLiqManualOverride = true;
    });
    el('d3-modal-close-btn', 'click', () => hideModal(document.getElementById('d3-modal'))); // This ID exists
    el('sort-name', 'click', () => setComboSort('name')); // This ID exists
    el('sort-created', 'click', () => setComboSort('created')); // This ID exists
    el('override-modal-close-btn', 'click', () => hideModal(document.getElementById('override-modal'))); // This ID exists
    el('override-modal-cancel-btn', 'click', () => hideModal(document.getElementById('override-modal'))); // This ID exists
    el('override-modal-save-btn', 'click', saveComboFromModal); // This ID exists
    el('close-leg-modal-close-btn', 'click', () => hideModal(document.getElementById('close-leg-modal'))); // This ID exists
    el('close-leg-modal-cancel-btn', 'click', () => hideModal(document.getElementById('close-leg-modal'))); // This ID exists
    el('close-leg-modal-confirm-btn', 'click', confirmCloseLeg); // This ID exists
    el('confirm-add-legs-btn', 'click', prepareAddLegs); // This ID exists
    el('cancel-add-legs-btn', 'click', exitAddLegsMode); // This ID exists
    el('edit-leg-modal-close-btn', 'click', () => hideModal(document.getElementById('edit-leg-modal'))); // This ID exists
    el('edit-leg-modal-cancel-btn', 'click', () => hideModal(document.getElementById('edit-leg-modal'))); // This ID exists
    el('edit-leg-modal-confirm-btn', 'click', confirmEditLeg); // This ID exists
    el('select-all-combos-checkbox', 'change', toggleSelectAllCombos); // This ID exists
    el('global-theme-checkbox', 'change', toggleTheme); // This ID exists
    el('close-position-modal-close-btn', 'click', () => hideModal(document.getElementById('close-position-modal'))); // This ID exists
    el('close-position-modal-cancel-btn', 'click', () => hideModal(document.getElementById('close-position-modal'))); // This ID exists
    el('close-position-modal-confirm-btn', 'click', transmitCloseOrder); // This ID exists
    el('combo-order-modal-close-btn', 'click', () => hideModal(document.getElementById('combo-order-modal'))); // This ID exists
    el('combo-order-modal-cancel-btn', 'click', () => hideModal(document.getElementById('combo-order-modal'))); // This ID exists
    el('combo-order-modal-confirm-btn', 'click', transmitComboCloseOrder); // This ID exists
    el('combo-limit-price', 'input', updateComboPriceType); // This ID exists

    window.addEventListener('builder-open-risk-workspace', (event) => {
        const detail = event?.detail || {};
        const stagedLegs = Array.isArray(detail.legs) ? detail.legs : [];
        if (!stagedLegs.length) {
            alert('No staged legs available to profile.');
            return;
        }
        showRiskProfile({
            legs: stagedLegs,
            name: detail.name || 'Modeled Trade',
            sourceTab: detail.sourceTab || 'builder',
        });
    });

    const combosBody = document.getElementById('combos-table-body');
    if (combosBody) {
        combosBody.addEventListener('click', handleComboTableClick);
        combosBody.addEventListener('change', handleComboTableChange);
        combosBody.addEventListener('keydown', handleComboTableKeydown);
        combosBody.addEventListener('focusout', handleComboTableFocusOut);
    }
    console.log("Event listeners bound."); // Add log
}

// ... (fetchInitialData, updateData, requestLegDetails, manualRefreshPositions, savePortfolioSnapshot remain the same) ...
async function fetchInitialData() {
    const banner = document.getElementById('status-banner');
    renderPortfolioRiskDigestLoading();
    try {
        console.log("Fetching initial data..."); // Add log
        const res = await fetch(`${API_BASE_URL}/data`);
        if (!res.ok) throw new Error('Backend not responding');
        const data = await res.json();
        console.log(`Initial data received: ${data.length} items.`); // Add log
        portfolioData = Object.fromEntries(data.map(l => [l.conId, l]));
        renderLegsTable();
        updateCombosView(true);
        updateStatusBanner();
        loadPortfolioRiskDigest();

        const isSnapshot = Object.values(portfolioData).some(p => p.status === 'Snapshot');
        if (!isSnapshot) {
            console.log("Live mode: Queuing initial detail requests and starting update interval."); // Add log
            data.forEach(l => { if (l.status === 'Queued') { requestLegDetails(l.conId); }});
            if (updateInterval) clearInterval(updateInterval);
            updateInterval = setInterval(updateData, 2000);
        } else {
            console.log("Snapshot mode detected."); // Add log
            setStatusBannerState('snapshot', 'Status: Displaying portfolio snapshot from file. Live connection is off.');
            document.getElementById('save-snapshot-btn').style.display = 'none';
            document.getElementById('refresh-btn').style.display = 'none';
        }
    } catch(e) {
        console.error("Initial fetch failed:", e);
        setStatusBannerState('error', 'Status: Disconnected.');
        setTimeout(fetchInitialData, 5000);
    }
}

async function updateData() {
    try {
        // console.log("Updating data..."); // Potentially too noisy
        const pricesRes = await fetch(`${API_BASE_URL}/underlying_prices`);
        if (pricesRes.ok) {
            underlyingPrices = await pricesRes.json();
        }

        const res = await fetch(`${API_BASE_URL}/data`); if (!res.ok) return;
        const newData = await res.json();
        const newPortfolio = Object.fromEntries(newData.map(l => [l.conId, l]));

        let positionsChanged = Object.keys(portfolioData).length !== Object.keys(newPortfolio).length;
        if (!positionsChanged) {
            for(const conId in newPortfolio) {
                if(!portfolioData[conId] || newPortfolio[conId].position !== portfolioData[conId].position) {
                    positionsChanged = true;
                    break;
                }
            }
        }

        portfolioData = newPortfolio;
        if(positionsChanged) {
            console.log("Positions changed, re-rendering legs table."); // Add log
            renderLegsTable();
        } else {
            // console.log("Updating existing leg rows..."); // Potentially too noisy
            Object.values(newPortfolio).forEach(updateLegRow);
        }
        updateCombosView(false);
        updateStatusBanner();
        loadPortfolioRiskDigest();

    } catch(e) { console.error("Update loop error:", e); }
}

window.requestLegDetails = async function(conId) {
    try {
        // console.log(`Requesting details for ${conId}`); // Potentially too noisy
        await fetch(`${API_BASE_URL}/request_leg_data`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({conId:conId}) });
    } catch(e){ console.error(`Request failed for ${conId}:`, e); }
}

async function manualRefreshPositions() {
    console.log("Manual refresh requested."); // Add log
    const btn = document.getElementById('refresh-btn');
    btn.disabled = true; btn.textContent = 'Refreshing...';
    try { await fetch(`${API_BASE_URL}/refresh_positions`,{method:'POST'}); } catch(e){ console.error("Refresh failed:",e); }
    finally { setTimeout(() => { btn.disabled = false; btn.textContent = '🔄 Refresh Positions'; }, 2000); }
}

async function savePortfolioSnapshot() {
    console.log("Save snapshot requested."); // Add log
    const btn = document.getElementById('save-snapshot-btn');
    btn.disabled = true; btn.textContent = 'Saving...';
    try {
        const response = await fetch(`${API_BASE_URL}/generate_snapshot`);
        if (!response.ok) { throw new Error('Server failed to generate snapshot.'); }
        const data = await response.json();
        if (data.status === 'success') {
            alert(`Snapshot saved successfully as:\n${data.file}`);
        } else {
            throw new Error(data.error || 'Unknown error during snapshot generation.');
        }
    } catch (e) {
        console.error("Save snapshot failed:", e);
        alert(`Error saving snapshot: ${e.message}`);
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = '💾 Save Snapshot';
        }, 2000);
    }
}

function buildLegRowHtml(leg, isChecked) {
    const statusCell = leg.status === 'Queued'
        ? `<button onclick="requestLegDetails(${leg.conId})" class="btn-primary text-[10px] md:text-xs py-0.5 px-1.5">Load</button>`
        : getStatusSpan(leg.status);
    const price = underlyingPrices[leg.contract.symbol]
        ? `<span class="text-xs text-muted ml-2">$${underlyingPrices[leg.contract.symbol].toFixed(2)}</span>`
        : '';
    return `
        <td class="p-2"><input type="checkbox" class="leg-checkbox h-4 w-4 rounded form-checkbox" data-conid="${leg.conId}" ${isChecked ? 'checked' : ''}></td>
        <td class="p-2 whitespace-nowrap">${leg.description}${price}</td>
        <td class="p-2">${leg.account}</td><td class="p-2">${leg.position}</td>
        <td class="p-2" id="daily-pnl-${leg.conId}">${formatCurrency(leg.pnl.daily,true)}</td>
        <td class="p-2" id="unrealized-pnl-${leg.conId}">${formatCurrency(leg.pnl.unrealized,true)}</td>
        <td class="p-2" id="status-${leg.conId}">${statusCell}</td>
        <td class="p-2 text-center"><button onclick="openClosePositionModal(${leg.conId})" class="btn-danger text-[10px] md:text-xs py-0.5 px-1.5">Close</button></td>`;
}

function renderLegsTable() {
    const body = document.getElementById('legs-table-body'); if(!body) return;
    // console.log("Rendering legs table..."); // Potentially too noisy
    const checkedState = new Set();
    document.querySelectorAll('.leg-checkbox:checked').forEach(cb => { checkedState.add(parseInt(cb.dataset.conid)); });
    syncAccountFilterOptions();

    body.innerHTML = '';
    Object.values(portfolioData).sort((a,b) => (a.description||'').localeCompare(b.description||'')).forEach(l => {
        const r = document.createElement('tr'); r.id=`leg-row-${l.conId}`;
        r.innerHTML = buildLegRowHtml(l, checkedState.has(l.conId));
        body.appendChild(r);
    });
    filterLegsTable();
    loadPortfolioRiskDigest();
}

function updateLegRow(l) {
    const r = document.getElementById(`leg-row-${l.conId}`); if (!r) return;
    const price = underlyingPrices[l.contract.symbol] ? `<span class="text-xs text-muted ml-2">$${underlyingPrices[l.contract.symbol].toFixed(2)}</span>` : '';
    r.cells[1].innerHTML = `${l.description}${price}`;
    r.cells[4].innerHTML = formatCurrency(l.pnl.daily,true);
    r.cells[5].innerHTML = formatCurrency(l.pnl.unrealized,true);
    const statusCell = l.status === 'Queued' ? `<button onclick="requestLegDetails(${l.conId})" class="btn-primary text-[10px] md:text-xs py-0.5 px-1.5">Load</button>`: getStatusSpan(l.status);
    r.cells[6].innerHTML = statusCell;
}

function getComboIndexFromNode(node) {
    const row = node?.closest?.('tr[data-original-index]');
    if (!row) return null;
    const index = Number(row.dataset.originalIndex);
    return Number.isInteger(index) ? index : null;
}

function handleComboTableClick(event) {
    const actionButton = event.target.closest('button[data-action]');
    if (actionButton) {
        event.stopPropagation();
        const comboIndex = getComboIndexFromNode(actionButton);
        if (comboIndex == null) return;
        const action = actionButton.dataset.action;
        if (action === 'add-leg') enterAddLegsMode(comboIndex);
        if (action === 'profile') showRiskProfile({ comboIndex, sourceTab: 'combos' });
        if (action === 'close-combo') openCloseEntireComboModal(comboIndex);
        if (action === 'delete-combo') deleteCombo(comboIndex);
        return;
    }

    const legActionButton = event.target.closest('button[data-leg-action]');
    if (legActionButton) {
        const comboIndex = Number(legActionButton.dataset.comboIndex);
        const legIndex = Number(legActionButton.dataset.legIndex);
        if (!Number.isInteger(comboIndex) || !Number.isInteger(legIndex)) return;
        const legAction = legActionButton.dataset.legAction;
        if (legAction === 'edit-close' || legAction === 'close-leg') openCloseLegModal(comboIndex, legIndex);
        if (legAction === 'trade-leg') openTradeComboLegModal(comboIndex, legIndex);
        if (legAction === 'edit-leg') openEditLegModal(comboIndex, legIndex);
        return;
    }

    if (event.target.closest('input,button')) return;
    const comboIndex = getComboIndexFromNode(event.target);
    if (comboIndex != null) toggleComboDetails(comboIndex);
}

function handleComboTableChange(event) {
    const comboCheckbox = event.target.closest('.combo-checkbox');
    if (comboCheckbox) {
        const comboIndex = Number(comboCheckbox.dataset.comboIndex);
        if (!Number.isInteger(comboIndex)) return;
        if (comboCheckbox.checked) selectedCombos.add(comboIndex);
        else selectedCombos.delete(comboIndex);
        updateComboAggregation();
    }
}

function handleComboTableKeydown(event) {
    const nameInput = event.target.closest('input[data-role="combo-name"]');
    if (!nameInput) return;
    if (event.key === 'Enter') {
        event.preventDefault();
        nameInput.blur();
    }
}

function handleComboTableFocusOut(event) {
    const nameInput = event.target.closest('input[data-role="combo-name"]');
    if (!nameInput) return;
    const comboIndex = getComboIndexFromNode(nameInput);
    if (comboIndex == null) return;
    updateComboName(comboIndex, nameInput.value);
}


function setComboSort(column) {
    if (comboSort.column === column) { comboSort.direction = comboSort.direction === 'asc' ? 'desc' : 'asc'; }
    else { comboSort.column = column; comboSort.direction = 'asc'; }
    updateCombosView(true);
}

function syncGroupFilterOptions(groupFilter, uniqueGroups, currentFilterValue) {
    groupFilter.innerHTML = '<option value="All">All Groups</option>';
    uniqueGroups.sort().forEach((group) => {
        const option = document.createElement('option');
        option.value = group;
        option.textContent = group;
        groupFilter.appendChild(option);
    });

    if (currentFilterValue && uniqueGroups.includes(currentFilterValue)) {
        groupFilter.value = currentFilterValue;
    } else if (currentFilterValue !== 'All') {
        groupFilter.value = 'All';
    }
    return groupFilter.value || 'All';
}

function buildComboSummaryRowHtml(combo, originalIndex, metrics, live, earliestExpiry, isChecked) {
    const createdString = combo.createdAt
        ? new Date(combo.createdAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).replace(/ /g, '-')
        : '—';
    const dteInfo = calculateDTE(earliestExpiry);
    const dteString = earliestExpiry !== '99999999'
        ? `<div class="font-semibold">${dteInfo.days}d</div><div class="text-muted text-[10px]">${dteInfo.date}</div>`
        : 'N/A';

    return `
        <td class="p-2"><input type="checkbox" class="combo-checkbox h-4 w-4 rounded form-checkbox" data-combo-index="${originalIndex}" ${isChecked ? 'checked' : ''}></td>
        <td class="p-2 font-semibold text-primary">
            <div class="flex items-center"><svg class="expand-icon w-4 h-4 mr-2 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                <input type="text" data-role="combo-name" class="input-styles bg-transparent border-none focus:bg-tertiary p-1 w-full text-sm font-medium" value="${combo.name}"/>
            </div></td>
        <td class="p-2 text-center bg-tertiary/30">${formatCurrency(metrics.costBasis)}</td>
        <td class="p-2 text-center bg-tertiary/30">${formatPnlWithPercent(metrics.totalReturn, metrics.costBasis)}</td>
        <td class="p-2 text-center bg-tertiary/30">${formatPnlWithPercent(metrics.dailyPnl, metrics.costBasis)}</td>
        <td class="p-2 text-center bg-tertiary/50">${coloredGreek(metrics.delta)}</td>
        <td class="p-2 text-center bg-tertiary/50">${coloredGreek(metrics.theta)}</td>
        <td class="p-2 text-center bg-tertiary/50">${coloredGreek(metrics.vega)}</td>
        <td class="p-2 text-center bg-tertiary/50">${coloredGreek(metrics.gamma)}</td>
        <td class="p-2 text-center text-xs text-muted">${createdString}</td>
        <td class="p-2 text-center text-xs">${dteString}</td>
        <td class="p-2 text-center text-sm space-x-1 whitespace-nowrap">
            <button data-action="add-leg" class="btn-link text-green-600 dark:text-green-500 text-xs p-1">Add</button>
            <button data-action="profile" class="btn-link text-blue-600 dark:text-blue-500 text-xs p-1"${!live ? ' disabled' : ''}>Profile</button>
            <button data-action="close-combo" class="btn-link text-red-600 dark:text-red-500 text-xs p-1"${!live ? ' disabled' : ''}>Close</button>
            <button data-action="delete-combo" class="btn-link text-gray-500 hover:text-red-500 dark:hover:text-red-400 text-xs p-1">Del</button></td>`;
}

function buildComboDetailsRowHtml(combo, originalIndex) {
    let detailsHtml = `<td colspan="12" class="p-0"><div class="p-2 bg-primary"><table class="min-w-full text-xs"><thead><tr class="text-muted"><th class="p-1.5 text-left">Position</th><th class="p-1.5 text-left">Status</th><th class="p-1.5 text-left">Qty</th><th class="p-1.5 text-left">Cost Basis</th><th class="p-1.5 text-left">Return</th><th class="p-1.5 text-left">Delta</th><th class="p-1.5 text-left">IV</th><th class="p-1.5 text-left">Und. Price</th><th class="p-1.5 text-left">Actions</th></tr></thead><tbody>`;
    (combo.legs || []).forEach((comboLeg, legIndex) => {
        const twsLeg = portfolioData[comboLeg.conId];
        if (twsLeg) {
            const isClosed = comboLeg.status === 'closed';
            const rowClass = isClosed ? 'text-muted italic' : 'text-secondary';
            const ratio = getComboLegRatio(comboLeg, twsLeg);
            const legCostBasis = getComboLegCostBasis(comboLeg, twsLeg);
            const marketValue = parseNumber(twsLeg.marketValue, 0) * ratio;
            const returnVal = isClosed ? comboLeg.realizedPnl : marketValue - legCostBasis;
            const m = getLegMultiplier(twsLeg);
            const delta = parseNumber(twsLeg.greeks.delta, 0) * parseNumber(comboLeg.qty, 0) * m;
            const actionButtons = isClosed
                ? `<button data-leg-action="edit-close" data-combo-index="${originalIndex}" data-leg-index="${legIndex}" class="btn-link text-yellow-600 dark:text-yellow-500 text-[10px] p-0.5">Edit P&L</button>`
                : `<button data-leg-action="trade-leg" data-combo-index="${originalIndex}" data-leg-index="${legIndex}" class="btn-link text-blue-600 dark:text-blue-500 text-[10px] p-0.5">Trade</button>
                   <button data-leg-action="edit-leg" data-combo-index="${originalIndex}" data-leg-index="${legIndex}" class="btn-link text-yellow-600 dark:text-yellow-500 text-[10px] p-0.5 ml-1">Edit</button>
                   <button data-leg-action="close-leg" data-combo-index="${originalIndex}" data-leg-index="${legIndex}" class="btn-link text-red-600 dark:text-red-500 text-[10px] p-0.5 ml-1">Close P&L</button>`;
            detailsHtml += `<tr class="border-t border-border-color ${rowClass}"><td class="p-1.5">${twsLeg.description}</td><td class="p-1.5">${isClosed ? 'Closed' : getStatusSpan(twsLeg.status)}</td><td class="p-1.5">${comboLeg.qty}</td><td class="p-1.5">${formatCurrency(legCostBasis)}</td><td class="p-1.5">${formatCurrency(returnVal, true)}</td><td class="p-1.5">${isClosed ? '0.00' : formatNumber(delta)}</td><td class="p-1.5">${formatNumber(twsLeg.greeks.iv, 3) || 'N/A'}</td><td class="p-1.5">${formatNumber(twsLeg.greeks.undPrice)}</td><td class="p-1.5 whitespace-nowrap" data-leg-index="${legIndex}">${actionButtons}</td></tr>`;
        } else {
            detailsHtml += `<tr class="border-t border-border-color text-muted italic"><td class="p-1.5" colspan="9">Position data for ConId ${comboLeg.conId} not available.</td></tr>`;
        }
    });
    detailsHtml += '</tbody></table></div></td>';
    return detailsHtml;
}

function renderCustomCombos() {
    const body = document.getElementById('combos-table-body');
    const groupFilter = document.getElementById('group-filter-select');
    const nameFilterInput = document.getElementById('combo-filter-input');
    if(!body || !groupFilter || !nameFilterInput) return;
    customCombos = normalizeCombos(customCombos);
    // console.log("Rendering combos table..."); // Potentially too noisy

    const nameFilter = nameFilterInput.value.toLowerCase();
    const uniqueGroups = [...new Set(customCombos.map(c => c.group || 'Default'))];
    const currentFilterValue = groupFilter.value;
    const selectedGroup = syncGroupFilterOptions(groupFilter, uniqueGroups, currentFilterValue);

    const sortedCombos = [...customCombos].sort((a, b) => {
        let valA = (comboSort.column === 'name') ? a.name.toLowerCase() : new Date(a.createdAt || 0);
        let valB = (comboSort.column === 'name') ? b.name.toLowerCase() : new Date(b.createdAt || 0);
        if (valA < valB) return comboSort.direction === 'asc' ? -1 : 1;
        if (valA > valB) return comboSort.direction === 'asc' ? 1 : -1;
        return 0;
    });

    document.querySelectorAll('.sortable-header').forEach(th => th.classList.remove('sort-asc', 'sort-desc'));
    const activeSortHeader = document.getElementById(`sort-${comboSort.column}`);
    if (activeSortHeader) activeSortHeader.classList.add(comboSort.direction === 'asc' ? 'sort-asc' : 'sort-desc');

    body.innerHTML = '';
    let memory = new Set(expandedCombos);
    let combosToRender = 0;

    sortedCombos.forEach((combo) => {
        const originalIndex = customCombos.indexOf(combo); // Get index in ORIGINAL array for stable ID
        const group = combo.group || 'Default';
        if ((selectedGroup !== 'All' && group !== selectedGroup) || (nameFilter && !combo.name.toLowerCase().includes(nameFilter))) return;
        combosToRender++;

        const data = computeComboMetrics(combo);
        const live = data.live;
        const earliestExpiry = data.earliestExpiry;

        const r = document.createElement('tr'); const isExpanded = memory.has(originalIndex);
        r.className = `combo-row cursor-pointer hover:bg-hover ${isExpanded ? "expanded bg-hover" : ""}`; // Use CSS var
        r.dataset.originalIndex = originalIndex;
        r.innerHTML = buildComboSummaryRowHtml(combo, originalIndex, data, live, earliestExpiry, selectedCombos.has(originalIndex));
        body.appendChild(r);


        if (isExpanded) {
            const detailsRow = document.createElement('tr');
            detailsRow.className = 'details-row'; // Uses CSS variable for background
            detailsRow.innerHTML = buildComboDetailsRowHtml(combo, originalIndex);
            body.appendChild(detailsRow);
        }
    });
    if (combosToRender === 0) {
        body.innerHTML = '<tr><td colspan="12" class="text-center p-4 text-muted">No combos match your filters.</td></tr>';
    }
    updateComboAggregation();
}

// ... (Functions openClosePositionModal to transmitComboCloseOrder remain largely the same) ...
window.openClosePositionModal = function(conId, qty) {
    const leg = portfolioData[conId];
    if (!leg) { console.error("Position data not found for conId:", conId); return; }
    const closeQty = qty === undefined ? leg.position : qty;
    positionToClose = { conId: leg.conId, qty: closeQty, account: leg.account };
    const action = closeQty > 0 ? 'SELL' : 'BUY';
    const description = `${action} ${Math.abs(closeQty)} of ${leg.description}`;
    document.getElementById('close-position-description').textContent = description;
    const priceInput = document.getElementById('close-limit-price');
    const orderTypeSelect = document.getElementById('close-order-type');
    const multiplier = parseFloat(leg.contract.multiplier || 100);
    if (leg.marketValue && leg.position !== 0 && multiplier !== 0) {
        priceInput.value = (leg.marketValue / (leg.position * multiplier)).toFixed(2);
    } else { priceInput.value = ''; }
    orderTypeSelect.onchange = () => {
        document.querySelector('label[for="close-limit-price"]').parentElement.style.display = (orderTypeSelect.value === 'LMT') ? '' : 'none';
    };
    orderTypeSelect.onchange();
    document.getElementById('close-position-modal').classList.remove('hidden');
    priceInput.focus();
}

async function transmitCloseOrder() {
    if (!positionToClose) return;
    const btn = document.getElementById('close-position-modal-confirm-btn');
    const orderType = document.getElementById('close-order-type').value;
    const limitPriceEl = document.getElementById('close-limit-price');
    let limitPrice = orderType === 'LMT' ? parseFloat(limitPriceEl.value) : null;
    const tif = document.getElementById('close-tif').value;
    if (orderType === 'LMT' && (isNaN(limitPrice) || limitPrice <= 0)) { alert('Valid positive Limit Price required.'); return; }
    const payload = { legs: [{ conId: positionToClose.conId, qty: -positionToClose.qty }], orderType, limitPrice, account: positionToClose.account, tif }; // qty sign reversed for closing
    btn.disabled = true; const prevText = btn.textContent; btn.textContent = 'Sending...';
    try {
        const resp = await fetch(`${API_BASE_URL}/place_order`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
        if (!resp.ok) { let errText = 'Order failed.'; try { errText = (await resp.json()).error || errText; } catch (e) {} throw new Error(errText); }
        const data = await resp.json();
        alert('Order sent: ' + (data.message || 'Check TWS to transmit.'));
        hideModal(document.getElementById('close-position-modal'));
    } catch (e) { alert(`Error: ${e.message}`); }
    finally { btn.disabled = false; btn.textContent = prevText; positionToClose = null; }
}

window.openTradeComboLegModal = function(comboIndex, legIndex) {
    const combo = customCombos[comboIndex]; if (!combo || !combo.legs || !combo.legs[legIndex]) return;
    const leg = combo.legs[legIndex]; openClosePositionModal(leg.conId, leg.qty);
};

window.openCloseEntireComboModal = function(comboIndex) {
    const combo = customCombos[comboIndex]; if (!combo) return;
    const openLegs = (combo.legs || []).filter(l => l.status === 'open');
    if (openLegs.length === 0) { alert("Combo has no open legs."); return; }
    const firstTwsLeg = portfolioData[openLegs[0].conId]; if (!firstTwsLeg) { alert("TWS data missing for first leg."); return; }
    comboToClose = { symbol: firstTwsLeg.contract.symbol, legs: openLegs, account: firstTwsLeg.account };
    const modalTitle = document.getElementById('combo-order-modal-title');
    const modalBody = document.getElementById('combo-order-modal-body');
    const bidAskSpan = document.getElementById('combo-market-data');
    modalTitle.textContent = `Close Combo: ${combo.name}`;
    bidAskSpan.innerHTML = 'Loading...';
    let bodyHtml = `<table class="min-w-full text-sm"><thead class="text-muted"><tr><th class="p-1.5 text-left">Action</th><th class="p-1.5 text-left">Qty</th><th class="p-1.5 text-left">Description</th></tr></thead><tbody>`;
    let netMarketValue = 0, comboBid = 0, comboAsk = 0;
    openLegs.forEach(leg => {
        const twsLeg = portfolioData[leg.conId];
        if (twsLeg) {
            const action = leg.qty > 0 ? 'SELL' : 'BUY'; // Action to close
            const color = action === 'SELL' ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400';
            bodyHtml += `<tr class="border-t border-border-color"><td class="p-1.5 font-semibold ${color}">${action}</td><td class="p-1.5">${Math.abs(leg.qty)}</td><td class="p-1.5">${twsLeg.description}</td></tr>`;
            let priceForCalc = (twsLeg.bid + twsLeg.ask) / 2; if (twsLeg.last && twsLeg.last > 0) priceForCalc = twsLeg.last; if (priceForCalc <= 0 && twsLeg.close && twsLeg.close > 0) priceForCalc = twsLeg.close; priceForCalc = priceForCalc || 0;
            const multiplier = parseFloat(twsLeg.contract.multiplier || 100);
            const legValue = priceForCalc * Math.abs(leg.qty) * multiplier;
            netMarketValue += (action === 'SELL' ? legValue : -legValue);
            const legBid = twsLeg.bid || priceForCalc; const legAsk = twsLeg.ask || priceForCalc; const legQtyAbs = Math.abs(leg.qty);
            if (action === 'SELL') { comboBid += legBid * legQtyAbs; comboAsk += legAsk * legQtyAbs; }
            else { comboBid -= legAsk * legQtyAbs; comboAsk -= legBid * legQtyAbs; }
        }
    });
    bodyHtml += `</tbody></table>`; modalBody.innerHTML = bodyHtml;
    const comboMultiplier = 1; // Display per unit
    bidAskSpan.innerHTML = `Bid: <span class="font-semibold text-green-600 dark:text-green-400">${(comboBid / comboMultiplier).toFixed(2)}</span> / Ask: <span class="font-semibold text-red-600 dark:text-red-400">${(comboAsk / comboMultiplier).toFixed(2)}</span>`;
    document.getElementById('combo-limit-price').value = (netMarketValue / comboMultiplier).toFixed(2);
    updateComboPriceType(); document.getElementById('combo-order-modal').classList.remove('hidden');
}


function updateComboPriceType() {
    const priceInput = document.getElementById('combo-limit-price');
    const typeLabel = document.getElementById('combo-price-type');
    const price = parseFloat(priceInput.value);
    if (isNaN(price)) { typeLabel.textContent = '--'; typeLabel.className = 'bg-tertiary text-secondary px-3 py-2 rounded-r-md font-semibold text-xs border border-l-0 border-border-color'; }
    else if (price < 0) { typeLabel.textContent = 'Credit'; typeLabel.className = 'bg-green-600 text-white px-3 py-2 rounded-r-md font-semibold text-xs border border-l-0 border-green-700'; }
    else { typeLabel.textContent = 'Debit'; typeLabel.className = 'bg-red-600 text-white px-3 py-2 rounded-r-md font-semibold text-xs border border-l-0 border-red-700'; }
}


async function transmitComboCloseOrder() {
    if (!comboToClose) return;
    const btn = document.getElementById('combo-order-modal-confirm-btn');
    const orderType = document.getElementById('combo-order-type').value;
    const limitPriceEl = document.getElementById('combo-limit-price');
    let limitPrice = orderType === 'LMT' ? parseFloat(limitPriceEl.value) : null;
    if (orderType === 'LMT' && isNaN(limitPrice)) { alert('Valid Net Limit Price required.'); return; }
    const payloadLegs = comboToClose.legs.map(l => ({ conId: l.conId, qty: -l.qty })); // Reverse qty to close
    const payload = { legs: payloadLegs, orderType, limitPrice, symbol: comboToClose.symbol, account: comboToClose.account, tif: document.getElementById('combo-tif').value };
    btn.disabled = true; btn.textContent = 'Sending...';
    try {
        const resp = await fetch(`${API_BASE_URL}/place_order`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
        if (!resp.ok) { let errText = 'Combo order failed.'; try { errText = (await resp.json()).error || errText; } catch (e) {} throw new Error(errText); }
        const data = await resp.json();
        alert('Combo order sent: ' + (data.message || 'Check TWS to transmit.'));
        hideModal(document.getElementById('combo-order-modal'));
    } catch (e) { alert(`Error: ${e.message}`); }
    finally { btn.disabled = false; btn.textContent = 'Send Combo Order'; comboToClose = null; }
}


// ... (prepareComboEditor, showComboBuilderModal, updateTempLeg, saveComboFromModal remain the same) ...
function prepareComboEditor(selectedCheckboxes) {
    if (!selectedCheckboxes || selectedCheckboxes.length === 0) {
        // Error already handled in the button's event listener
        return;
    }
    tempComboLegs = [];
    selectedCheckboxes.forEach(cb => {
        const conId = parseInt(cb.dataset.conid), twsLeg = portfolioData[conId];
        if (twsLeg) tempComboLegs.push({ conId, description: twsLeg.description, twsQty: twsLeg.position, twsCostBasis: twsLeg.costBasis, qty: twsLeg.position, costBasis: null });
    });
    showComboBuilderModal();
}

function showComboBuilderModal() {
    const modal = document.getElementById('override-modal'), modalBody = document.getElementById('override-modal-body'), modalTitle = document.getElementById('override-modal-title');
    if (!modal || !modalBody || !modalTitle) return;
    modalTitle.textContent = addLegsMode.enabled ? `Add Legs to: ${customCombos[addLegsMode.comboIndex].name}` : 'Create Custom Combo';
    let tableHtml = `<table class="min-w-full text-sm"><thead class="text-muted"><tr><th class="p-1.5 text-left">Position</th><th class="p-1.5 text-left">TWS Qty</th><th class="p-1.5 text-left">TWS Cost</th><th class="p-1.5 text-left">Combo Qty</th><th class="p-1.5 text-left">Combo Cost (per share/contract)</th></tr></thead><tbody>`;
    tempComboLegs.forEach((leg, index) => {
        tableHtml += `<tr class="border-t border-border-color"><td class="p-1.5">${leg.description}</td><td class="p-1.5">${leg.twsQty}</td><td class="p-1.5">${formatCurrency(leg.twsCostBasis)}</td>
            <td class="p-1.5"><input type="number" value="${leg.qty}" oninput="updateTempLeg(${index}, 'qty', this.value)" class="input-styles px-2 py-1 w-20"></td>
            <td class="p-1.5"><input type="number" step="0.01" placeholder="Optional" oninput="updateTempLeg(${index}, 'costBasis', this.value)" class="input-styles px-2 py-1 w-28"></td></tr>`;
    });
    modalBody.innerHTML = tableHtml + `</tbody></table>`;
    modal.classList.remove('hidden');
}

window.updateTempLeg = function(index, field, value) {
    if (index < tempComboLegs.length) {
        const parsed = parseFloat(value);
        if (field === 'costBasis') {
            tempComboLegs[index][field] = (value === '' || isNaN(parsed)) ? null : parsed;
        } else {
            tempComboLegs[index][field] = isNaN(parsed) ? 0 : parsed;
        }
    }
}

function saveComboFromModal() {
    const newLegs = tempComboLegs.map(leg => {
        let finalCostBasis = null;
        if (leg.costBasis != null && !isNaN(leg.costBasis)) {
            const twsLeg = portfolioData[leg.conId];
            const multiplier = parseFloat(twsLeg?.contract?.multiplier || 100);
            const qty = leg.qty;
            if (qty !== 0 && multiplier !== 0) {
                 let totalCost = leg.costBasis * Math.abs(qty) * multiplier;
                 finalCostBasis = (qty > 0) ? totalCost : -totalCost;
            }
        }
        return { conId: leg.conId, qty: leg.qty, costBasis: finalCostBasis, status: 'open', realizedPnl: 0 };
    }).filter(leg => leg.qty !== 0);

    if (newLegs.length === 0) {
        alert("Cannot save a combo with no legs or only zero-quantity legs.");
        return;
    }

    if (addLegsMode.enabled) {
        const combo = customCombos[addLegsMode.comboIndex];
        if (combo) {
            if (!combo.legs) combo.legs = [];
            combo.legs.push(...newLegs);
        }
        exitAddLegsMode();
    } else {
        const name = document.getElementById('combo-name-input').value.trim();
        const group = document.getElementById('combo-group-input').value.trim() || 'Default';
        if (!name) { /* Alert handled in button listener */ return; }
        customCombos.push({ name, group, legs: newLegs, createdAt: new Date().toISOString() });
        document.getElementById('combo-name-input').value = ''; document.getElementById('combo-group-input').value = '';
    }

    saveCombosToServer();
    updateCombosView(true);
    hideModal(document.getElementById('override-modal'));
    document.querySelectorAll('.leg-checkbox:checked').forEach(cb => cb.checked = false);
    const selectAll = document.getElementById('select-all-checkbox');
    if(selectAll) selectAll.checked = false;
    tempComboLegs = [];
}


// ... (openCloseLegModal, confirmCloseLeg, openEditLegModal, confirmEditLeg remain the same) ...
window.openCloseLegModal = function(comboIndex, legIndex) {
    legToClose = { comboIndex, legIndex };
    const leg = customCombos[comboIndex].legs[legIndex], twsLeg = portfolioData[leg.conId];
    if (!twsLeg) { alert("Cannot close leg - TWS data not found."); return; } // Add check
    document.getElementById('close-leg-description').textContent = `${twsLeg.description} (Qty: ${leg.qty})`;
    const priceInput = document.getElementById('close-leg-price');
    priceInput.value = (leg.status === 'closed' && leg.closingPrice != null) ? leg.closingPrice : '';
    priceInput.placeholder = `e.g., 3.50 (price per contract)`;
    document.getElementById('close-leg-modal').classList.remove('hidden');
    priceInput.focus();
}

function confirmCloseLeg() {
    const { comboIndex, legIndex } = legToClose; if (comboIndex === null) return;
    const price = parseFloat(document.getElementById('close-leg-price').value);
    if (isNaN(price)) { alert('Please enter a valid closing price.'); return; }
    const leg = customCombos[comboIndex].legs[legIndex], twsLeg = portfolioData[leg.conId];
    if (!twsLeg) { alert("Cannot close leg - TWS data not found."); return; } // Add check
    const multiplier = parseFloat(twsLeg?.contract?.multiplier || 100);
    let closingValue = price * Math.abs(leg.qty) * multiplier;
    if (leg.qty > 0) closingValue = closingValue; // Selling long = Credit
    else closingValue = -closingValue; // Buying short = Debit
    let legCostBasis = leg.costBasis;
    if (legCostBasis == null && twsLeg) {
        const ratio = twsLeg.position !== 0 ? leg.qty / twsLeg.position : 0;
        legCostBasis = twsLeg.costBasis * ratio;
    }
    legCostBasis = legCostBasis || 0;
    leg.realizedPnl = closingValue - legCostBasis;
    leg.status = 'closed'; leg.closingPrice = price;
    saveCombosToServer(); updateCombosView(true);
    hideModal(document.getElementById('close-leg-modal'));
    legToClose = { comboIndex: null, legIndex: null };
}

window.openEditLegModal = function(comboIndex, legIndex) {
    legToEdit = { comboIndex, legIndex };
    const leg = customCombos[comboIndex].legs[legIndex], twsLeg = portfolioData[leg.conId];
    if (!twsLeg) { alert("Cannot edit leg - TWS data not found."); return; } // Add check
    const multiplier = parseFloat(twsLeg?.contract?.multiplier || 100);
    document.getElementById('edit-leg-description').textContent = twsLeg.description;
    const qtyIn = document.getElementById('edit-leg-qty'), costIn = document.getElementById('edit-leg-cost');
    qtyIn.value = leg.qty;
    costIn.value = (leg.costBasis != null && leg.qty !== 0 && multiplier !== 0)
        ? (Math.abs(leg.costBasis) / (Math.abs(leg.qty) * multiplier)).toFixed(4)
        : '';
    document.getElementById('edit-leg-modal').classList.remove('hidden');
    qtyIn.focus();
}

function confirmEditLeg() {
    const { comboIndex, legIndex } = legToEdit; if (comboIndex === null) return;
    const leg = customCombos[comboIndex].legs[legIndex], twsLeg = portfolioData[leg.conId];
    if (!twsLeg) { alert("Cannot save edit - TWS data missing."); return; } // Add check
    const multiplier = parseFloat(twsLeg?.contract?.multiplier || 100);
    const newQty = parseInt(document.getElementById('edit-leg-qty').value);
    const newCostPerContract = parseFloat(document.getElementById('edit-leg-cost').value);
    if (isNaN(newQty)) { alert('Please enter a valid quantity.'); return; }
    leg.qty = newQty;
    if (!isNaN(newCostPerContract) && newQty !== 0 && multiplier !== 0) {
        let totalCost = newCostPerContract * Math.abs(newQty) * multiplier;
        leg.costBasis = (newQty > 0) ? totalCost : -totalCost;
    } else { leg.costBasis = null; }
    saveCombosToServer(); updateCombosView(true);
    hideModal(document.getElementById('edit-leg-modal'));
    legToEdit = { comboIndex: null, legIndex: null };
}

// ... (enterAddLegsMode, exitAddLegsMode, prepareAddLegs, deleteCombo, toggleComboDetails remain the same) ...
window.enterAddLegsMode = function(comboIndex) {
    const combo = customCombos[comboIndex];
    const firstLegConId = combo.legs?.[0]?.conId;
    const firstLeg = firstLegConId ? portfolioData[firstLegConId] : null; // Get TWS data for first leg
    if (!firstLeg) {
        alert("Cannot enter Add Legs mode - TWS data for the combo's first leg is missing.");
        return; // Prevent entering add mode if data is missing
    }
    addLegsMode = { enabled: true, comboIndex, symbol: firstLeg.contract?.symbol || '' };

    // Switch to portfolio tab
    const portfolioTabButton = document.querySelector('.tab-btn[data-tab="portfolio"]');
    if (portfolioTabButton) portfolioTabButton.click();
    else console.error("Portfolio tab button not found.");

    document.getElementById('create-combo-section').classList.add('hidden');
    const banner = document.getElementById('add-leg-mode-banner');
    document.getElementById('add-leg-target-combo').textContent = `Adding to: ${combo.name}`;
    banner.classList.remove('hidden');
    document.getElementById('filter-ticker').value = addLegsMode.symbol; // Pre-fill filter
    filterLegsTable(); // Apply filter
}

function exitAddLegsMode() {
    addLegsMode = { enabled: false, comboIndex: null, symbol: '' };
    document.getElementById('create-combo-section').classList.remove('hidden');
    document.getElementById('add-leg-mode-banner').classList.add('hidden');
    // Clear filters
    selectedAccountFilter = 'All';
    const accountFilter = document.getElementById('filter-account');
    if (accountFilter) accountFilter.value = 'All';
    document.getElementById('filter-ticker').value = '';
    document.getElementById('filter-expiry').value = '';
    document.getElementById('filter-strike').value = '';
    filterLegsTable(); // Re-apply empty filter
    // Optionally switch back to combos tab if not already there
    const combosTabButton = document.querySelector('.tab-btn[data-tab="combos"]');
    if (combosTabButton && !combosTabButton.classList.contains('active')) {
        // combosTabButton.click(); // Decided against auto-switching back
    }
    // Clear selections
    document.querySelectorAll('.leg-checkbox:checked').forEach(cb => cb.checked = false);
    const selectAll = document.getElementById('select-all-checkbox');
    if(selectAll) selectAll.checked = false;
}

function prepareAddLegs() {
    const selected = document.querySelectorAll('#legs-table-body tr:not([style*="display: none"]) .leg-checkbox:checked');
    if (selected.length === 0) { alert("Please select at least one leg to add."); return; }
    prepareComboEditor(selected); // Call the existing editor function
}

function updateComboName(comboIndex, nextName) {
    if (!Number.isInteger(comboIndex) || comboIndex < 0 || comboIndex >= customCombos.length) return;
    const trimmed = String(nextName || '').trim();
    if (!trimmed) return;
    if (customCombos[comboIndex].name === trimmed) return;
    customCombos[comboIndex].name = trimmed;
    saveCombosToServer();
    comboRenderCacheKey = '';
}

function deleteCombo(i) {
    if (confirm(`Are you sure you want to delete "${customCombos[i].name}"? This cannot be undone.`)) {
        customCombos.splice(i, 1);
        selectedCombos.delete(i); // Remove from selection if deleted
        // Adjust indices in selectedCombos greater than the deleted index
        const updatedSelection = new Set();
        selectedCombos.forEach(idx => {
            if (idx > i) updatedSelection.add(idx - 1);
            else if (idx < i) updatedSelection.add(idx);
        });
        selectedCombos = updatedSelection;

        saveCombosToServer();
        updateCombosView(true); // Re-render after deletion
    }
}

function toggleComboDetails(i) {
    if (expandedCombos.has(i)) expandedCombos.delete(i);
    else {
        expandedCombos.add(i);
        // Request data for legs if queued
        const combo = customCombos[i];
        if (combo && combo.legs) {
             combo.legs.forEach(leg => {
                 const twsLeg = portfolioData[leg.conId];
                 if (twsLeg && twsLeg.status === 'Queued') {
                     requestLegDetails(leg.conId);
                 }
             });
        }
    }
    updateCombosView(true); // Re-render to show/hide details
}

// <-- FIX: Corrected function name -->
function toggleSelectAll(e) { document.querySelectorAll('#legs-table-body tr:not([style*="display: none"]) .leg-checkbox').forEach(cb => { cb.checked = e.target.checked; }); }

function filterLegsTable() {
    const account = selectedAccountFilter || 'All';
    const ticker = document.getElementById('filter-ticker').value.toLowerCase();
    const expiry = document.getElementById('filter-expiry').value;
    const strike = document.getElementById('filter-strike').value;

    document.querySelectorAll('#legs-table-body tr').forEach(r => {
        const conId = r.querySelector('.leg-checkbox')?.dataset.conid; if (!conId) return;
        const leg = portfolioData[conId]; if (!leg) return;

        const accountMatch = account === 'All' || String(leg.account || '') === account;
        const symbolMatch = !ticker || (leg.contract.symbol || '').toLowerCase().includes(ticker);
        const expiryMatch = !expiry || (leg.contract.expiry || '').toString().includes(expiry);
        const strikeMatch = !strike || (leg.contract.strike || '').toString().includes(strike);

        r.style.display = (accountMatch && symbolMatch && expiryMatch && strikeMatch) ? '' : 'none';
    });
     // Uncheck select-all if filtering hides some rows
     const selectAll = document.getElementById('select-all-checkbox');
     if(selectAll) selectAll.checked = false;
}

function setStatusBannerState(state, text) {
    const banner = document.getElementById('status-banner');
    if (!banner) return;
    banner.textContent = text;
    banner.className = `status-banner status-${state}`;
}

function updateStatusBanner() {
    const t = Object.keys(portfolioData).length; const b = document.getElementById('status-banner'); if(!b) return;
    const isSnapshot = Object.values(portfolioData).some(p => p.status === 'Snapshot');
    if (isSnapshot) { setStatusBannerState('snapshot', 'Status: Displaying snapshot. Live connection off.'); return; }
    if (t === 0) { setStatusBannerState('idle', 'Status: Connected. No positions found.'); return; }
    const l = Object.values(portfolioData).filter(p => p.status && p.status.startsWith('Live')).length;
    setStatusBannerState('live', `Status: Connected. Live data for ${l} / ${t} positions.`);
}

function toggleSelectAllCombos(e) {
    const isChecked = e.target.checked;
    document.querySelectorAll('#combos-table-body .combo-checkbox').forEach((cb) => {
        // Only toggle visible checkboxes if filtering is applied? For now, toggle all matching.
        cb.checked = isChecked;
        const idx = parseInt(cb.dataset.comboIndex);
        if(isChecked) selectedCombos.add(idx);
        else selectedCombos.delete(idx);
    });
    updateComboAggregation();
}

// ... (updateComboAggregation, profileSelectedCombos remain the same) ...
function updateComboAggregation() {
    const aggBody = document.getElementById('combo-aggregation-body');
    if (!aggBody) return;

    let rowHtml;

    // Only show aggregation row when 2+ combos are selected — avoids redundant display with single-combo rows
    if (selectedCombos.size <= 1) {
        aggBody.innerHTML = '';
        return;
    } else {
        const agg = { costBasis: 0, totalReturn: 0, dailyPnl: 0, delta: 0, theta: 0, vega: 0, gamma: 0 };
        selectedCombos.forEach(comboIndex => {
            const combo = customCombos[comboIndex];
            if (!combo) return;
            (combo.legs || []).forEach(leg => {
                const tws = portfolioData[leg.conId];
                const legCost = getComboLegCostBasis(leg, tws);
                agg.costBasis += legCost;
                if(leg.status === 'closed') agg.totalReturn += leg.realizedPnl || 0;
                else {
                    if (tws) {
                        const ratio = getComboLegRatio(leg, tws);
                        const multiplier = getLegMultiplier(tws);
                        agg.totalReturn += (parseNumber(tws.marketValue, 0) * ratio) - legCost;
                        agg.dailyPnl += parseNumber(tws.pnl?.daily, 0) * ratio;
                        agg.delta += parseNumber(tws.greeks?.delta, 0) * parseNumber(leg.qty, 0) * multiplier;
                        agg.theta += parseNumber(tws.greeks?.theta, 0) * parseNumber(leg.qty, 0) * multiplier;
                        agg.vega += parseNumber(tws.greeks?.vega, 0) * parseNumber(leg.qty, 0) * multiplier;
                        agg.gamma += parseNumber(tws.greeks?.gamma, 0) * parseNumber(leg.qty, 0) * multiplier;
                    }
                }
            });
        });

        rowHtml = `
            <tr class="bg-blue-100 dark:bg-blue-900/30 border-b-2 border-blue-400 dark:border-blue-600">
                <td class="p-2"></td>
                <td class="p-2 text-left font-semibold text-primary">Selected Totals (${selectedCombos.size})</td>
                <td class="p-2 text-center bg-tertiary/30">${formatCurrency(agg.costBasis)}</td>
                <td class="p-2 text-center bg-tertiary/30">${formatPnlWithPercent(agg.totalReturn, agg.costBasis)}</td>
                <td class="p-2 text-center bg-tertiary/30">${formatPnlWithPercent(agg.dailyPnl, agg.costBasis)}</td>
                <td class="p-2 text-center bg-tertiary/50">${coloredGreek(agg.delta)}</td>
                <td class="p-2 text-center bg-tertiary/50">${coloredGreek(agg.theta)}</td>
                <td class="p-2 text-center bg-tertiary/50">${coloredGreek(agg.vega)}</td>
                <td class="p-2 text-center bg-tertiary/50">${coloredGreek(agg.gamma)}</td>
                <td class="p-2"></td>
                <td class="p-2"></td>
                <td class="p-2 text-center"><button id="agg-profile-btn" class="btn-link text-blue-600 dark:text-blue-500 text-xs p-1">Profile</button></td>
            </tr>
        `;
    }

    aggBody.innerHTML = rowHtml;

    const aggProfileBtn = document.getElementById('agg-profile-btn');
    if (aggProfileBtn) {
        aggProfileBtn.addEventListener('click', profileSelectedCombos);
    }
}


function profileSelectedCombos() {
    const legsForProfile = [];
    const aggregatedLegs = {};
    selectedCombos.forEach(comboIndex => {
        const combo = customCombos[comboIndex];
        if (combo) {
            (combo.legs || []).forEach(leg => {
                if (leg.status === 'open') {
                    const twsLeg = portfolioData[leg.conId];
                    const legCostBasis = getComboLegCostBasis(leg, twsLeg);

                    if (aggregatedLegs[leg.conId]) {
                        aggregatedLegs[leg.conId].qty += leg.qty;
                        aggregatedLegs[leg.conId].costBasis += (legCostBasis || 0);
                    } else {
                        aggregatedLegs[leg.conId] = {
                            conId: leg.conId,
                            qty: leg.qty,
                            costBasis: (legCostBasis || 0)
                        };
                    }
                }
            });
        }
    });

    for (const conId in aggregatedLegs) {
        if (aggregatedLegs[conId].qty !== 0) {
             legsForProfile.push(aggregatedLegs[conId]);
        }
    }


    if (legsForProfile.length > 0) {
        showRiskProfile({ legs: legsForProfile, name: `Aggregated (${selectedCombos.size})`, sourceTab: 'combos' });
    } else {
        alert('No open legs in selected combos to profile.');
    }
}

function getRiskReferenceCostBasis() {
    const sumCost = (currentRiskProfileLegs || []).reduce((sum, leg) => sum + parseNumber(leg.costBasis, 0), 0);
    return Math.max(0, Math.abs(sumCost));
}

function getNearestIndexByValue(values, target) {
    if (!Array.isArray(values) || values.length === 0) return -1;
    let nearestIndex = 0;
    let nearestDiff = Math.abs(parseNumber(values[0], 0) - target);
    for (let i = 1; i < values.length; i++) {
        const diff = Math.abs(parseNumber(values[i], 0) - target);
        if (diff < nearestDiff) {
            nearestDiff = diff;
            nearestIndex = i;
        }
    }
    return nearestIndex;
}

function formatAxisCurrency(value) {
    const num = parseNumber(value, 0);
    const abs = Math.abs(num);
    const sign = num < 0 ? '-' : '';
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
    return `${sign}$${abs.toFixed(0)}`;
}

function formatPercentFromBasis(value, basis) {
    if (!basis || basis <= 0) return '—';
    const pct = (parseNumber(value, 0) / basis) * 100;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
}

function clearRiskOverlayPanels() {
    const legsPanel = document.getElementById('risk-legs-panel');
    if (legsPanel) legsPanel.innerHTML = '';
    currentRiskCrosshairPrice = null;
    currentRiskCrosshairIndex = -1;
    setRiskCursorChips(null, null, null);
    RISK_STRIP_DEFS.forEach((def) => setRiskStripValue(def.key, null));
}

function setRiskModalView(view) {
    if (view === 'table' || view === 'sgpv' || view === 'graph') {
        riskActiveView = view;
    } else {
        riskActiveView = 'graph';
    }
    const graphView = document.getElementById('risk-graph-view');
    const tableView = document.getElementById('risk-table-view');
    const sgpvView = document.getElementById('risk-sgpv-view');
    const graphBtn = document.getElementById('risk-view-graph-btn');
    const tableBtn = document.getElementById('risk-view-table-btn');
    const sgpvBtn = document.getElementById('risk-view-sgpv-btn');
    if (graphView) graphView.classList.toggle('hidden', riskActiveView !== 'graph');
    if (tableView) tableView.classList.toggle('hidden', riskActiveView !== 'table');
    if (sgpvView) sgpvView.classList.toggle('hidden', riskActiveView !== 'sgpv');
    if (graphBtn) graphBtn.classList.toggle('active', riskActiveView === 'graph');
    if (tableBtn) tableBtn.classList.toggle('active', riskActiveView === 'table');
    if (sgpvBtn) sgpvBtn.classList.toggle('active', riskActiveView === 'sgpv');

    if (riskActiveView === 'table') renderRiskTable();
    if (riskActiveView === 'sgpv') {
        renderSgpvContextNote();
        drawSgpvChart();
    }
    enforceRiskModalLayout();
}

function setRiskCursorChips(price, points, basis) {
    const chips = document.getElementById('risk-cursor-chips');
    if (!chips) return;
    if (!points || !Array.isArray(points) || points.length === 0 || price == null) {
        chips.innerHTML = '';
        return;
    }
    const spot = parseNumber(currentRiskProfileData?.metrics?.current_und_price, NaN);
    const pctFromSpot = Number.isFinite(spot) && spot !== 0 ? ((parseNumber(price, 0) - spot) / spot) * 100 : NaN;
    const spotDeltaText = Number.isFinite(pctFromSpot) ? ` ${pctFromSpot >= 0 ? '+' : ''}${pctFromSpot.toFixed(2)}%` : '';
    let html = `<span class="risk-chip risk-chip-primary">Px ${formatNumber(price, 2)}${spotDeltaText}</span>`;
    points.slice(0, 4).forEach((point) => {
        const value = parseNumber(point.parsed?.y, 0);
        const lineColor = point.dataset?.borderColor || '#7dd3fc';
        html += `<span class="risk-chip" style="border-color:${lineColor}88;color:${lineColor}">${point.dataset?.label || 'Curve'} ${formatNumber(value, 2)} | ${formatPercentFromBasis(value, basis)}</span>`;
    });
    chips.innerHTML = html;
}

function formatRiskStripMetricValue(metricKey, value) {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—';
    if (metricKey === 'pnl') {
        return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}`;
    }
    return `${value >= 0 ? '+' : ''}${formatNumber(value, 2)}`;
}

function setRiskStripValue(metricKey, value) {
    const def = RISK_STRIP_DEFS.find((item) => item.key === metricKey);
    if (!def) return;
    const valueEl = document.getElementById(def.valueId);
    if (!valueEl) return;
    valueEl.textContent = formatRiskStripMetricValue(metricKey, value);
    if (typeof value !== 'number' || Number.isNaN(value)) {
        valueEl.style.color = 'var(--text-secondary)';
        return;
    }
    if (metricKey === 'pnl') {
        valueEl.style.color = value >= 0 ? '#34d399' : '#f87171';
    } else {
        valueEl.style.color = 'var(--text-secondary)';
    }
}

function setRiskStripMarker(price) {
    Object.values(riskStripCharts).forEach((chart) => {
        if (!chart?.options?.plugins?.annotation?.annotations) return;
        chart.options.plugins.annotation.annotations.cursor = {
            type: 'line',
            scaleID: 'x',
            value: parseNumber(price, 0),
            borderColor: 'rgba(250, 204, 21, 0.85)',
            borderWidth: 1.2,
            borderDash: [4, 4]
        };
        chart.update('none');
    });
}

function updateRiskCrosshair(price) {
    if (!currentRiskChartPriceRange || currentRiskChartPriceRange.length === 0) return;
    if (price == null || Number.isNaN(parseNumber(price, NaN))) return;

    const idx = getNearestIndexByValue(currentRiskChartPriceRange, price);
    if (idx < 0) return;

    const nextPrice = parseNumber(currentRiskChartPriceRange[idx], 0);
    if (currentRiskCrosshairIndex === idx && currentRiskCrosshairPrice === nextPrice) return;
    currentRiskCrosshairIndex = idx;
    currentRiskCrosshairPrice = nextPrice;

    if (riskChart?.options?.plugins?.annotation?.annotations) {
        riskChart.options.plugins.annotation.annotations.crosshair = {
            type: 'line',
            scaleID: 'x',
            value: currentRiskCrosshairPrice,
            borderColor: 'rgba(250, 204, 21, 0.82)',
            borderWidth: 1.2,
            borderDash: [4, 4]
        };
        riskChart.update('none');
    }

    setRiskStripMarker(currentRiskCrosshairPrice);
    RISK_STRIP_DEFS.forEach((def) => {
        const series = currentRiskStripSeries[def.key];
        if (!Array.isArray(series) || series.length === 0) {
            setRiskStripValue(def.key, null);
            return;
        }
        setRiskStripValue(def.key, parseNumber(series[idx], 0));
    });
}

function destroyRiskStripCharts() {
    Object.values(riskStripCharts).forEach((chart) => {
        if (chart && typeof chart.destroy === 'function') chart.destroy();
    });
    riskStripCharts = {};
    currentRiskStripSeries = {};
}

function drawRiskStripCharts(priceRange, greekCurves, pnlCurve, markerPrice) {
    destroyRiskStripCharts();
    if (!Array.isArray(priceRange) || priceRange.length === 0 || !greekCurves) return;

    currentRiskStripSeries = {
        pnl: Array.isArray(pnlCurve) ? pnlCurve : [],
        delta: Array.isArray(greekCurves.delta) ? greekCurves.delta : [],
        theta: Array.isArray(greekCurves.theta) ? greekCurves.theta : [],
        wtvega: Array.isArray(greekCurves.vega) ? greekCurves.vega : [],
    };

    RISK_STRIP_DEFS.forEach((def) => {
        const canvas = document.getElementById(def.id);
        const values = currentRiskStripSeries[def.key];
        if (!canvas || !Array.isArray(values) || values.length === 0) return;
        canvas.style.height = '68px';
        canvas.style.width = '100%';
        const ctx = canvas.getContext('2d');
        const series = priceRange.map((price, index) => ({
            x: parseNumber(price, 0),
            y: parseNumber(values[index], 0),
        }));
        // Gradient fill for the strip area
        const gradFill = ctx.createLinearGradient(0, 0, 0, 68);
        gradFill.addColorStop(0, def.color + '28');
        gradFill.addColorStop(1, def.color + '04');
        riskStripCharts[def.key] = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    data: series,
                    borderColor: def.color,
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.28,
                    fill: { target: 'origin', above: gradFill, below: gradFill }
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: Math.max(window.devicePixelRatio || 1, 2),
                animation: false,
                layout: { padding: { top: 32, bottom: 4, left: 0, right: 0 } },
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false },
                    annotation: { annotations: {} }
                },
                scales: {
                    x: { type: 'linear', display: false },
                    y: { display: false }
                }
            }
        });
    });

    if (markerPrice != null) {
        updateRiskCrosshair(markerPrice);
    }
}

function getRiskTableSettingsFromControls() {
    const metric = document.getElementById('risk-table-metric')?.value || riskTableUiState.metric || 'pnl';
    const columns = parseInt(document.getElementById('risk-table-columns')?.value, 10);
    const rangePct = parseNumber(document.getElementById('risk-table-range')?.value, riskTableUiState.rangePct);
    const strikeStepsEachSide = parseInt(document.getElementById('risk-table-rows')?.value, 10);
    riskTableUiState = {
        metric: metric in RISK_TABLE_METRIC_DEFS ? metric : 'pnl',
        columns: Number.isInteger(columns) ? Math.min(40, Math.max(3, columns)) : riskTableUiState.columns,
        rangePct: Math.min(80, Math.max(1, rangePct)),
        strikeStepsEachSide: Number.isInteger(strikeStepsEachSide) ? Math.min(40, Math.max(2, strikeStepsEachSide)) : riskTableUiState.strikeStepsEachSide,
    };
    return riskTableUiState;
}

function syncRiskTableControls() {
    const metricEl = document.getElementById('risk-table-metric');
    const columnsEl = document.getElementById('risk-table-columns');
    const rangeEl = document.getElementById('risk-table-range');
    const rowsEl = document.getElementById('risk-table-rows');
    if (metricEl) metricEl.value = riskTableUiState.metric;
    if (columnsEl) columnsEl.value = String(riskTableUiState.columns);
    if (rangeEl) rangeEl.value = String(riskTableUiState.rangePct);
    if (rowsEl) rowsEl.value = String(riskTableUiState.strikeStepsEachSide);
}

function formatRiskTableCellValue(metric, value) {
    if (value == null || Number.isNaN(parseNumber(value, NaN))) return '—';
    const v = parseNumber(value, 0);
    const def = RISK_TABLE_METRIC_DEFS[metric] || RISK_TABLE_METRIC_DEFS.pnl;
    if (def.currency) {
        return `${v >= 0 ? '+' : ''}${Math.round(v).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}`;
    }
    if (def.suffix === '%') {
        return `${v >= 0 ? '+' : ''}${v.toFixed(def.digits)}%`;
    }
    return `${v >= 0 ? '+' : ''}${v.toFixed(def.digits)}`;
}

function getRiskHeatCellIntensity(value, minAbs, maxAbs) {
    if (value == null || Number.isNaN(parseNumber(value, NaN))) return null;
    const v = parseNumber(value, 0);
    const scale = Math.max(maxAbs, Math.abs(minAbs), 1e-9);
    return Math.min(1, Math.abs(v) / scale);
}

function getRiskHeatBandLabel(intensity) {
    if (intensity == null) return 'N/A';
    if (intensity >= 0.82) return 'Extreme';
    if (intensity >= 0.56) return 'Elevated';
    if (intensity >= 0.24) return 'Moderate';
    return 'Light';
}

function getRiskHeatCellStyle(value, minAbs, maxAbs) {
    if (value == null || Number.isNaN(parseNumber(value, NaN))) return '';
    const v = parseNumber(value, 0);
    const intensity = getRiskHeatCellIntensity(value, minAbs, maxAbs) ?? 0;
    const alpha = 0.1 + (intensity * 0.37);
    if (v >= 0) {
        const edge = intensity > 0.82 ? 'box-shadow: inset 0 0 0 1px rgba(16, 185, 129, 0.58);' : '';
        return `background: rgba(16, 185, 129, ${alpha.toFixed(3)}); color: #d1fae5; ${edge}`;
    }
    const edge = intensity > 0.82 ? 'box-shadow: inset 0 0 0 1px rgba(239, 68, 68, 0.62);' : '';
    return `background: rgba(239, 68, 68, ${alpha.toFixed(3)}); color: #fee2e2; ${edge}`;
}

function renderRiskTableLoading(message = 'Loading risk table...') {
    const body = document.getElementById('risk-table-body');
    const head = document.getElementById('risk-table-head');
    const summary = document.getElementById('risk-table-summary');
    const context = document.getElementById('risk-table-context');
    if (context) {
        context.innerHTML = `<div class="col-span-full text-center text-muted text-xs">${escapeHtml(message)}</div>`;
    }
    if (summary) summary.innerHTML = `<div class="col-span-4 text-center text-muted">${message}</div>`;
    if (head) head.innerHTML = '';
    if (body) body.innerHTML = `<tr><td colspan="4" class="p-3 text-center text-muted">${message}</td></tr>`;
}

function renderRiskTable() {
    const body = document.getElementById('risk-table-body');
    const head = document.getElementById('risk-table-head');
    const summary = document.getElementById('risk-table-summary');
    const context = document.getElementById('risk-table-context');
    if (!body || !head || !summary) return;
    const data = currentRiskTableData;
    const matrix = data?.matrix;

    if (!data || !matrix || !Array.isArray(matrix.price_axis) || matrix.price_axis.length === 0) {
        if (context) context.innerHTML = '<div class="col-span-full text-center text-muted text-xs">No matrix context available.</div>';
        summary.innerHTML = '<div class="col-span-4 text-center text-muted">No risk table data available.</div>';
        head.innerHTML = '';
        body.innerHTML = '<tr><td colspan="4" class="p-3 text-center text-muted">No matrix.</td></tr>';
        return;
    }

    const metricOptions = Array.isArray(matrix.metric_options) ? matrix.metric_options : Object.keys(RISK_TABLE_METRIC_DEFS);
    if (!metricOptions.includes(riskTableUiState.metric)) {
        riskTableUiState.metric = metricOptions[0] || 'pnl';
    }

    const metricSelect = document.getElementById('risk-table-metric');
    if (metricSelect) {
        metricSelect.innerHTML = metricOptions
            .map((metricKey) => `<option value="${metricKey}">${RISK_TABLE_METRIC_DEFS[metricKey]?.label || metricKey}</option>`)
            .join('');
        metricSelect.value = riskTableUiState.metric;
    }

    const metric = riskTableUiState.metric;
    const priceAxis = matrix.price_axis || [];
    const pctAxis = matrix.price_pct_axis || [];
    const timeColumns = matrix.time_columns || [];
    const surfaces = matrix.metric_surfaces || {};
    const surface = surfaces[metric];

    if (!Array.isArray(surface) || surface.length === 0) {
        if (context) context.innerHTML = `<div class="col-span-full text-center text-muted text-xs">Metric "${escapeHtml(metric)}" has no matrix context.</div>`;
        summary.innerHTML = `<div class="col-span-4 text-center text-muted">Metric "${metric}" has no values.</div>`;
        head.innerHTML = '';
        body.innerHTML = '<tr><td colspan="4" class="p-3 text-center text-muted">No rows.</td></tr>';
        return;
    }

    summary.innerHTML = `
        <div><div class="text-xs text-muted">Spot</div><div class="font-semibold text-primary">$${formatNumber(data.spot, 2)}</div></div>
        <div><div class="text-xs text-muted">Metric</div><div class="font-semibold text-primary">${RISK_TABLE_METRIC_DEFS[metric]?.label || metric}</div></div>
        <div><div class="text-xs text-muted">Columns</div><div class="font-semibold text-primary">${timeColumns.length}</div></div>
        <div><div class="text-xs text-muted">Rows</div><div class="font-semibold text-primary">${priceAxis.length}</div></div>
    `;

    const flatValues = surface.flat().map((v) => parseNumber(v, 0)).filter((v) => Number.isFinite(v));
    const minValue = flatValues.length ? Math.min(...flatValues) : 0;
    const maxValue = flatValues.length ? Math.max(...flatValues) : 0;
    const timeAtmIndex = Math.max(0, timeColumns.findIndex((col) => parseNumber(col.days, 0) === 0));
    const atmRowIndex = parseInt(matrix.atm_row_index, 10);
    const metricLabel = RISK_TABLE_METRIC_DEFS[metric]?.label || metric;
    const pctMin = pctAxis.length ? parseNumber(pctAxis[0], 0) : 0;
    const pctMax = pctAxis.length ? parseNumber(pctAxis[pctAxis.length - 1], 0) : 0;
    const priceMin = parseNumber(priceAxis[0], parseNumber(data.spot, 0));
    const priceMax = parseNumber(priceAxis[priceAxis.length - 1], parseNumber(data.spot, 0));
    const rowStep = priceAxis.length > 1
        ? Math.abs(parseNumber(priceAxis[1], 0) - parseNumber(priceAxis[0], 0))
        : 0;
    const rowStepText = rowStep > 0 ? ` | step ${formatNumber(rowStep, 2)}` : '';
    const normalizedAtmRowIndex = Number.isInteger(atmRowIndex) && atmRowIndex >= 0 && atmRowIndex < priceAxis.length ? atmRowIndex : 0;
    const atmPrice = parseNumber(priceAxis[normalizedAtmRowIndex], parseNumber(data.spot, 0));
    const nowCol = timeColumns[timeAtmIndex] || { label: 'T+0', days: 0, date: '' };
    const expCol = timeColumns[timeColumns.length - 1] || nowCol;

    if (context) {
        context.innerHTML = `
            <div class="risk-table-context-item">
                <div class="risk-table-context-label">Axes</div>
                <div class="risk-table-context-value">Rows: Underlying vs spot delta<br>Columns: horizon (DTE)</div>
            </div>
            <div class="risk-table-context-item">
                <div class="risk-table-context-label">Coverage</div>
                <div class="risk-table-context-value">$${formatNumber(priceMin, 2)} to $${formatNumber(priceMax, 2)} | ${pctMin >= 0 ? '+' : ''}${pctMin.toFixed(1)}% to ${pctMax >= 0 ? '+' : ''}${pctMax.toFixed(1)}%${rowStepText}</div>
            </div>
            <div class="risk-table-context-item">
                <div class="risk-table-context-label">Anchors</div>
                <div class="risk-table-context-value">ATM row $${formatNumber(atmPrice, 2)} | NOW ${escapeHtml(nowCol.label || `T+${parseInt(nowCol.days, 10) || 0}`)} | EXP ${escapeHtml(expCol.label || `T+${parseInt(expCol.days, 10) || 0}`)}</div>
            </div>
            <div class="risk-table-context-item">
                <div class="risk-table-context-label">${escapeHtml(metricLabel)} Scale</div>
                <div class="risk-table-context-value">
                    ${formatRiskTableCellValue(metric, minValue)} / 0 / ${formatRiskTableCellValue(metric, maxValue)}
                    <div class="risk-table-scale-bar">
                        <span class="risk-table-scale-neg">Loss</span>
                        <span class="risk-table-scale-zero">Flat</span>
                        <span class="risk-table-scale-pos">Gain</span>
                    </div>
                </div>
            </div>
        `;
    }

    let headHtml = '<tr><th class="p-2 text-left risk-matrix-sticky-col"><div class="risk-matrix-th-main">Underlying</div><div class="risk-matrix-th-sub">Rows: price and spot delta</div></th>';
    timeColumns.forEach((col, colIdx) => {
        const atmColCls = colIdx === timeAtmIndex ? ' risk-matrix-atm-col' : '';
        const isNowCol = colIdx === timeAtmIndex;
        const isExpCol = colIdx === timeColumns.length - 1;
        const colDays = parseInt(col.days, 10);
        const colLabel = col.label || (Number.isInteger(colDays) ? `T+${colDays}` : 'T+?');
        const meta = `${Number.isInteger(colDays) ? `${colDays}d` : ''}${col.date ? `${Number.isInteger(colDays) ? ' | ' : ''}${col.date}` : ''}`;
        const badgeHtml = isNowCol
            ? '<span class="risk-matrix-badge">NOW</span>'
            : (isExpCol ? '<span class="risk-matrix-badge risk-matrix-badge-exp">EXP</span>' : '');
        headHtml += `<th class="p-2 text-center${atmColCls}">
            <div class="risk-matrix-th-main">${escapeHtml(colLabel)}${badgeHtml}</div>
            <div class="risk-matrix-th-sub">${escapeHtml(meta)}</div>
        </th>`;
    });
    headHtml += '</tr>';
    head.innerHTML = headHtml;

    let bodyHtml = '';
    for (let rowIdx = 0; rowIdx < priceAxis.length; rowIdx++) {
        const price = parseNumber(priceAxis[rowIdx], 0);
        const pct = parseNumber(pctAxis[rowIdx], 0);
        const isAtmRow = rowIdx === normalizedAtmRowIndex;
        const pctText = `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
        const rowBadge = isAtmRow ? '<span class="risk-matrix-row-badge">ATM</span>' : '';
        bodyHtml += `<tr class="${isAtmRow ? 'risk-matrix-atm-row' : ''}">
            <td class="p-2 font-mono risk-matrix-sticky-col">
                <div class="risk-matrix-row-main"><span>${formatNumber(price, 2)}</span>${rowBadge}</div>
                <div class="risk-matrix-row-sub">${pctText} vs spot</div>
            </td>`;
        for (let colIdx = 0; colIdx < timeColumns.length; colIdx++) {
            const rawVal = surface[colIdx]?.[rowIdx];
            const style = getRiskHeatCellStyle(rawVal, minValue, maxValue);
            const atmColCls = colIdx === timeAtmIndex ? ' risk-matrix-atm-col' : '';
            const intensity = getRiskHeatCellIntensity(rawVal, minValue, maxValue);
            const magnitude = getRiskHeatBandLabel(intensity);
            const numeric = parseNumber(rawVal, NaN);
            const signLabel = Number.isFinite(numeric) ? (numeric > 0 ? 'Gain' : (numeric < 0 ? 'Loss' : 'Flat')) : 'N/A';
            const colDays = parseInt(timeColumns[colIdx]?.days, 10);
            const colLabel = timeColumns[colIdx]?.label || (Number.isInteger(colDays) ? `T+${colDays}` : 'T+?');
            const note = isAtmRow && colIdx === timeAtmIndex ? 'ATM x NOW' : (isAtmRow ? 'ATM row' : (colIdx === timeAtmIndex ? 'NOW col' : ''));
            const tooltip = `${metricLabel}: ${formatRiskTableCellValue(metric, rawVal)} | ${signLabel}, ${magnitude} | Px ${formatNumber(price, 2)} (${pctText}) @ ${colLabel}`;
            bodyHtml += `<td class="p-1.5 font-mono text-center${atmColCls}" style="${style}" title="${escapeHtml(tooltip)}">
                <div class="risk-matrix-cell">
                    <div class="risk-matrix-cell-main">${formatRiskTableCellValue(metric, rawVal)}</div>
                    ${note ? `<div class="risk-matrix-cell-note">${note}</div>` : ''}
                </div>
            </td>`;
        }
        bodyHtml += '</tr>';
    }
    body.innerHTML = bodyHtml;
}

async function loadRiskTableData(legs, metrics) {
    if (!Array.isArray(legs) || legs.length === 0) return;
    syncRiskTableControls();
    const settings = getRiskTableSettingsFromControls();
    renderRiskTableLoading();
    const daysToExpiry = parseNumber(metrics?.days_to_expiry, 0);
    const requestedSteps = [0, ...(metrics?.time_steps || []), daysToExpiry]
        .map((v) => parseInt(v, 10))
        .filter((v) => Number.isInteger(v) && v >= 0);

    const strikeStepPct = settings.rangePct / Math.max(1, settings.strikeStepsEachSide);

    try {
        const resp = await fetch(`${API_BASE_URL}/get_risk_table`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                legs,
                spot: metrics?.current_und_price,
                time_steps: requestedSteps,
                columns: settings.columns,
                strike_steps_each_side: settings.strikeStepsEachSide,
                strike_step_pct: strikeStepPct,
            })
        });
        if (!resp.ok) {
            let errorText = 'Failed to load risk table.';
            try { errorText = (await resp.json()).error || errorText; } catch (e) {}
            throw new Error(errorText);
        }
        currentRiskTableData = await resp.json();
        renderRiskTable();
    } catch (error) {
        currentRiskTableData = null;
        renderRiskTableLoading(error.message);
    }
}

function estimateNetLiqForSgpv(legs) {
    if (!Array.isArray(legs) || legs.length === 0) return 100000;
    let estimate = 0;
    legs.forEach((leg) => {
        const tws = portfolioData[leg.conId];
        const position = parseNumber(tws?.position, 0);
        if (!tws || position === 0) return;
        const ratio = parseNumber(leg.qty, 0) / position;
        estimate += Math.abs(parseNumber(tws.marketValue, 0) * ratio);
    });
    if (estimate <= 0) {
        estimate = Math.abs(legs.reduce((sum, leg) => sum + parseNumber(leg.costBasis, 0), 0));
    }
    return Math.max(estimate, 1);
}

function getSelectedSgpvAccount() {
    const select = document.getElementById('sgpv-account-select');
    return (select?.value || 'All').trim() || 'All';
}

function syncSgpvAccountOptions(accounts = []) {
    const select = document.getElementById('sgpv-account-select');
    if (!select) return;
    const current = getSelectedSgpvAccount();
    const sorted = Array.isArray(accounts)
        ? [...new Set(accounts.map((a) => String(a || '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b))
        : [];
    select.innerHTML = '<option value="All">All Accounts</option>';
    sorted.forEach((account) => {
        const option = document.createElement('option');
        option.value = account;
        option.textContent = account;
        select.appendChild(option);
    });
    const nextValue = (current === 'All' || sorted.includes(current)) ? current : 'All';
    select.value = nextValue;
}

function renderSgpvContextNote() {
    const note = document.getElementById('sgpv-context-note');
    if (!note) return;
    if (!currentRiskAccountContext) {
        note.textContent = '';
        return;
    }
    const netLiq = currentRiskAccountContext?.net_liq || {};
    const maint = currentRiskAccountContext?.maintenance_margin || {};
    const cp = currentRiskAccountContext?.client_portal || {};
    const tws = currentRiskAccountContext?.tws_account_summary || {};
    const ageSec = parseNumber(tws.age_sec, NaN);
    const source = netLiq.source || 'unknown';
    const netLiqValue = parseNumber(netLiq.value, NaN);
    const maintValue = parseNumber(maint.value, NaN);
    const netLiqText = Number.isFinite(netLiqValue)
        ? netLiqValue.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
        : 'N/A';
    const maintText = Number.isFinite(maintValue)
        ? maintValue.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
        : 'N/A';
    const cpText = cp.enabled ? (cp.available ? 'available' : 'enabled/unavailable') : 'disabled';
    const twsAgeText = Number.isFinite(ageSec) ? `${ageSec.toFixed(1)}s` : 'N/A';
    note.textContent = `NetLiq source: ${source}. NetLiq: ${netLiqText}. Maint Margin: ${maintText}. TWS summary age: ${twsAgeText}. Client Portal: ${cpText}.`;
}

async function loadAccountRiskContext(legs) {
    const accounts = getSortedAccountsFromPortfolio();
    syncSgpvAccountOptions(accounts);
    const selectedAccount = getSelectedSgpvAccount();

    try {
        const response = await fetch(`${API_BASE_URL}/get_account_risk_context`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                selected_account: selectedAccount,
                legs: Array.isArray(legs) ? legs : [],
            }),
        });
        if (!response.ok) {
            let errorText = 'Failed to load account risk context.';
            try { errorText = (await response.json()).error || errorText; } catch (e) {}
            throw new Error(errorText);
        }
        currentRiskAccountContext = await response.json();
        syncSgpvAccountOptions(currentRiskAccountContext.accounts || accounts);
        if (!sgpvNetLiqManualOverride) {
            const backendValue = parseNumber(currentRiskAccountContext?.net_liq?.value, NaN);
            if (Number.isFinite(backendValue) && backendValue > 0) {
                sgpvUiState.netLiq = backendValue;
            }
        }
        syncSgpvControls();
        renderSgpvContextNote();
    } catch (error) {
        currentRiskAccountContext = null;
        renderSgpvContextNote();
        const note = document.getElementById('sgpv-context-note');
        if (note) note.textContent = error.message;
    }
}

function renderSgpvLoading(message = 'Loading SGPV simulation...') {
    const summary = document.getElementById('sgpv-summary');
    if (summary) summary.innerHTML = `<div class="col-span-4 text-center text-muted">${message}</div>`;
    const canvas = document.getElementById('sgpv-chart-canvas');
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
}

function syncSgpvControls() {
    const netLiqInput = document.getElementById('sgpv-netliq-input');
    const columnsInput = document.getElementById('sgpv-columns-input');
    const rangeInput = document.getElementById('sgpv-range-input');
    if (netLiqInput && sgpvUiState.netLiq != null) netLiqInput.value = String(Math.round(sgpvUiState.netLiq));
    if (columnsInput) columnsInput.value = String(sgpvUiState.columns);
    if (rangeInput) rangeInput.value = String(sgpvUiState.rangePct);
}

function getSgpvSettingsFromControls() {
    const netLiqRaw = parseNumber(document.getElementById('sgpv-netliq-input')?.value, NaN);
    const columns = parseInt(document.getElementById('sgpv-columns-input')?.value, 10);
    const rangePct = parseNumber(document.getElementById('sgpv-range-input')?.value, sgpvUiState.rangePct);
    sgpvUiState.columns = Number.isInteger(columns) ? Math.min(20, Math.max(3, columns)) : sgpvUiState.columns;
    sgpvUiState.rangePct = Math.min(90, Math.max(5, rangePct));
    sgpvUiState.strikeStepsEachSide = 11;
    if (Number.isFinite(netLiqRaw) && netLiqRaw > 0) sgpvUiState.netLiq = netLiqRaw;
    return sgpvUiState;
}

function renderSgpvSummary() {
    const summary = document.getElementById('sgpv-summary');
    if (!summary) return;
    if (!currentSgpvData?.metrics || !currentSgpvData?.thresholds) {
        summary.innerHTML = '<div class="col-span-4 text-center text-muted">No SGPV simulation data.</div>';
        return;
    }
    const m = currentSgpvData.metrics;
    const t = currentSgpvData.thresholds;
    const maintValue = parseNumber(currentRiskAccountContext?.maintenance_margin?.value, NaN);
    const accountLabel = currentRiskAccountContext?.selected_account || getSelectedSgpvAccount();
    summary.innerHTML = `
        <div><div class="text-xs text-muted">SGPV @ Spot (${accountLabel})</div><div class="font-semibold text-primary">${formatCurrency(m.sgpv_at_spot, true)}</div></div>
        <div><div class="text-xs text-muted">Ratio @ Spot</div><div class="font-semibold text-primary">${formatNumber(m.ratio_at_spot, 2)}x</div></div>
        <div><div class="text-xs text-muted">Open Restriction</div><div class="font-semibold text-amber-300">${formatCurrency(t.open_restriction_value)}</div></div>
        <div><div class="text-xs text-muted">Liquidation</div><div class="font-semibold text-red-300">${formatCurrency(t.liquidation_value)}</div></div>
        <div><div class="text-xs text-muted">Maint Margin</div><div class="font-semibold text-primary">${Number.isFinite(maintValue) ? formatCurrency(maintValue) : '<span class="text-muted">N/A</span>'}</div></div>
    `;
}

function drawSgpvChart() {
    if (!currentSgpvData) return;
    const canvas = document.getElementById('sgpv-chart-canvas');
    if (!canvas) return;
    if (sgpvChart) {
        sgpvChart.destroy();
        sgpvChart = null;
    }

    const data = currentSgpvData;
    const priceRange = data.price_range || [];
    const curves = data.curves || {};
    const metrics = data.metrics || {};
    const thresholds = data.thresholds || {};
    const breachRanges = data.breach_ranges || {};

    const toSeries = (curve) => priceRange.map((price, idx) => ({
        x: parseNumber(price, 0),
        y: parseNumber(curve?.[idx], 0),
    }));

    const datasets = [{
        label: 'T+0',
        data: toSeries(curves.t0_sgpv_curve || []),
        borderColor: '#5ac8ff',
        borderWidth: 2.6,
        pointRadius: 0,
        tension: 0.24,
    }];

    const interCurves = curves.intermediate_curves || {};
    const interColors = ['#37d1a8', '#f59e0b', '#d946ef', '#fb7185'];
    Object.keys(interCurves).forEach((key, idx) => {
        const stepMatch = key.match(/^t(\d+)_/);
        const stepLabel = stepMatch ? stepMatch[1] : key;
        datasets.push({
            label: `T+${stepLabel}`,
            data: toSeries(interCurves[key]),
            borderColor: interColors[idx % interColors.length],
            borderWidth: 1.6,
            pointRadius: 0,
            tension: 0.24,
            borderDash: [6, 5],
        });
    });

    datasets.push({
        label: `Expiry T+${parseNumber(metrics.days_to_expiry, 0)}`,
        data: toSeries(curves.exp_sgpv_curve || curves.t0_sgpv_curve || []),
        borderColor: '#38bdf8',
        borderWidth: 2.2,
        pointRadius: 0,
        tension: 0.22,
    });

    const allValues = datasets.flatMap((ds) => ds.data || []).map((p) => parseNumber(p?.y, 0));
    const minY = Math.min(0, ...allValues);
    const maxY = Math.max(0, ...allValues);
    const yPad = Math.max((maxY - minY) * 0.12, 100);
    const yMin = minY - yPad;
    const yMax = maxY + yPad;
    const spot = parseNumber(metrics.current_und_price, 0);
    const css = getComputedStyle(document.documentElement);
    const gridColor = css.getPropertyValue('--border-color').trim();
    const textColor = css.getPropertyValue('--text-primary').trim();
    const textMuted = css.getPropertyValue('--text-muted').trim();

    const annotations = {
        spot: {
            type: 'line',
            scaleID: 'x',
            value: spot,
            borderColor: 'rgba(250, 204, 21, 0.9)',
            borderWidth: 1.4,
            borderDash: [5, 4],
            label: {
                enabled: true,
                content: `ATM ${formatNumber(spot, 2)}`,
                position: 'start',
                backgroundColor: 'rgba(30, 41, 59, 0.85)',
                color: '#f8fafc',
                padding: 4,
                borderRadius: 4,
                yAdjust: -14,
            }
        }
    };
    (breachRanges.warning || []).forEach((range, idx) => {
        annotations[`warning_${idx}`] = {
            type: 'box',
            xMin: parseNumber(range[0], 0),
            xMax: parseNumber(range[1], 0),
            yMin,
            yMax,
            backgroundColor: 'rgba(245, 158, 11, 0.16)',
            borderWidth: 0,
        };
    });
    (breachRanges.liquidation || []).forEach((range, idx) => {
        annotations[`liq_${idx}`] = {
            type: 'box',
            xMin: parseNumber(range[0], 0),
            xMax: parseNumber(range[1], 0),
            yMin,
            yMax,
            backgroundColor: 'rgba(239, 68, 68, 0.2)',
            borderWidth: 0,
        };
    });

    sgpvChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: Math.max(window.devicePixelRatio || 1, 2),
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: textColor, usePointStyle: true, boxWidth: 8, boxHeight: 8 }
                },
                annotation: { annotations },
                tooltip: {
                    callbacks: {
                        label(ctx) {
                            const y = parseNumber(ctx.parsed?.y, 0);
                            return `${ctx.dataset.label}: ${Math.round(y).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'Underlying Price', color: textColor },
                    grid: { color: `${gridColor}66` },
                    ticks: { color: textColor, callback: (v) => formatNumber(parseNumber(v, 0), 0) }
                },
                xTop: {
                    type: 'linear',
                    position: 'top',
                    grid: { display: false },
                    ticks: {
                        color: textMuted,
                        callback(value) {
                            const priceAtTick = parseNumber(value, NaN);
                            if (!Number.isFinite(priceAtTick) || !spot) return '';
                            const pct = ((priceAtTick - spot) / spot) * 100;
                            return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
                        }
                    }
                },
                y: {
                    min: yMin,
                    max: yMax,
                    title: { display: true, text: 'SGPV ($)', color: textColor },
                    grid: { color: `${gridColor}88` },
                    ticks: { color: textColor, callback: (v) => formatAxisCurrency(v) }
                },
                yRatio: {
                    position: 'right',
                    min: yMin,
                    max: yMax,
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: 'SGPV / NetLiq (x)', color: textMuted },
                    ticks: {
                        color: textMuted,
                        callback(value) {
                            const netLiq = parseNumber(metrics.net_liq, 0);
                            if (!netLiq) return '—';
                            return `${(parseNumber(value, 0) / netLiq).toFixed(1)}x`;
                        }
                    }
                }
            }
        }
    });
}

async function loadSgpvData(legs, metrics) {
    if (!Array.isArray(legs) || legs.length === 0) return;
    if (!sgpvUiState.netLiq || sgpvUiState.netLiq <= 0) {
        sgpvUiState.netLiq = estimateNetLiqForSgpv(legs);
    }
    syncSgpvControls();
    const settings = getSgpvSettingsFromControls();
    renderSgpvLoading();
    const strikeStepPct = settings.rangePct / Math.max(1, settings.strikeStepsEachSide);
    const daysToExpiry = parseNumber(metrics?.days_to_expiry, 0);
    const requestedSteps = [0, ...(metrics?.time_steps || []), daysToExpiry]
        .map((v) => parseInt(v, 10))
        .filter((v) => Number.isInteger(v) && v >= 0);

    try {
        const resp = await fetch(`${API_BASE_URL}/get_sgpv_sim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                legs,
                spot: metrics?.current_und_price,
                selected_account: getSelectedSgpvAccount(),
                net_liq: settings.netLiq,
                columns: settings.columns,
                time_steps: requestedSteps,
                strike_steps_each_side: settings.strikeStepsEachSide,
                strike_step_pct: strikeStepPct,
            }),
        });
        if (!resp.ok) {
            let errorText = 'Failed to load SGPV simulation.';
            try { errorText = (await resp.json()).error || errorText; } catch (e) {}
            throw new Error(errorText);
        }
        currentSgpvData = await resp.json();
        sgpvUiState.netLiq = parseNumber(currentSgpvData?.metrics?.net_liq, settings.netLiq);
        renderSgpvSummary();
        if (riskActiveView === 'sgpv') drawSgpvChart();
    } catch (error) {
        currentSgpvData = null;
        renderSgpvLoading(error.message);
    }
}

function renderRiskCurvePanel(chartData, spotIndex, basis) {
    // Removed — curve values are shown in the tooltip instead
}

function renderRiskLegsPanel(legs) {
    const panel = document.getElementById('risk-legs-panel');
    if (!panel) return;
    if (!Array.isArray(legs) || legs.length === 0) {
        panel.innerHTML = '';
        return;
    }

    let html = '<div class="risk-overlay-title">Selected Legs</div>';
    legs.forEach((leg) => {
        const tws = portfolioData[leg.conId];
        const contract = tws?.contract || leg || {};
        const side = parseNumber(leg.qty, 0) >= 0 ? 'BUY' : 'SELL';
        const sideColor = side === 'BUY' ? '#10b981' : '#f87171';
        const strike = parseNumber(contract?.strike, 0);
        const right = String(contract?.right || '').toUpperCase();
        const expiry = contract?.expiry || '';
        const multiplier = tws
            ? getLegMultiplier(tws)
            : Math.max(1, parseNumber(leg.multiplier, 100));
        const unitDelta = tws ? parseNumber(tws.greeks?.delta, null) : null;
        const netDelta =
            unitDelta == null
                ? null
                : unitDelta * parseNumber(leg.qty, 0) * multiplier;
        html += `
            <div class="risk-overlay-leg">
                <span style="color:${sideColor}" class="font-semibold">${side} ${Math.abs(parseNumber(leg.qty, 0))}</span>
                <span class="truncate text-secondary">${expiry} ${strike || ''}${right}</span>
                <span class="font-mono text-muted">Δ ${netDelta == null ? '—' : formatNumber(netDelta, 1)}</span>
            </div>`;
    });
    panel.innerHTML = html;
}

// ========================================================================================
// --- TIME MODEL DATE LINE ROWS ---
// ========================================================================================
function renderTimeModelLines(datasets) {
    const linesEl = document.getElementById('risk-time-lines');
    const legendEl = document.getElementById('risk-time-legend-dots');
    if (!linesEl) return;

    if (!datasets || datasets.length === 0) {
        linesEl.innerHTML = '<div class="text-[10px] text-muted px-0.5">No time curves available.</div>';
        if (legendEl) legendEl.innerHTML = '';
        return;
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let html = '', legendHtml = '', hasLines = false;

    datasets.forEach((ds, idx) => {
        const label = String(ds.label || '');
        if (label === 'T+0' || label.startsWith('Expiry')) return;
        const daysMatch = label.match(/T\+(\d+)/);
        if (!daysMatch) return;

        hasLines = true;
        const days = parseInt(daysMatch[1], 10);
        const color = ds.borderColor || '#94a3b8';
        const isHidden = ds.hidden || false;

        const targetDate = new Date(today.getTime() + days * 86400000);
        const inputDateStr = targetDate.toISOString().slice(0, 10);
        const shortDate = targetDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

        legendHtml += `<span class="risk-time-dot" style="background:${color}; box-shadow: 0 0 5px ${color}66;" title="${label} — ${shortDate}"></span>`;

        const eyeOpen = `<svg xmlns="http://www.w3.org/2000/svg" style="width:11px;height:11px;display:inline;" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>`;

        html += `
            <div class="risk-time-line-row${isHidden ? ' risk-time-line-hidden' : ''}" data-ds-index="${idx}" data-days="${days}">
                <span class="risk-time-dot" style="background:${color};"></span>
                <svg xmlns="http://www.w3.org/2000/svg" class="risk-time-cal-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                <input type="date" class="risk-time-date-input" value="${inputDateStr}" data-ds-index="${idx}" title="${label} — ${shortDate}">
                <span class="risk-time-days-badge">${days}d</span>
                <button class="risk-time-toggle-btn" data-ds-index="${idx}" title="${isHidden ? 'Show curve' : 'Hide curve'}" type="button">
                    ${isHidden ? eyeOpen : '×'}
                </button>
            </div>`;
    });

    if (!hasLines) {
        linesEl.innerHTML = '<div class="text-[10px] text-muted px-0.5">No intermediate time curves loaded.</div>';
        if (legendEl) legendEl.innerHTML = '';
        return;
    }
    linesEl.innerHTML = html;
    if (legendEl) legendEl.innerHTML = legendHtml;

    // Wire date change events
    linesEl.querySelectorAll('.risk-time-date-input').forEach(input => {
        input.addEventListener('change', (e) => {
            const row = e.target.closest('.risk-time-line-row');
            if (!row) return;
            const dsIndex = parseInt(row.dataset.dsIndex, 10);
            const selectedDate = new Date(e.target.value + 'T00:00:00');
            const now = new Date(); now.setHours(0,0,0,0);
            const days = Math.max(0, Math.round((selectedDate.getTime() - now.getTime()) / 86400000));
            row.dataset.days = days;
            const badge = row.querySelector('.risk-time-days-badge');
            if (badge) badge.textContent = days + 'd';
            if (riskTimeEnabled && currentRiskProfileLegs && riskChart) {
                const ivShift = parseInt(document.getElementById('iv-slider')?.value || '0', 10) / 100.0;
                updatePnlCurveAtIndex(dsIndex, currentRiskProfileLegs, days, ivShift);
            }
        });
    });

    // Wire hide/show toggle buttons
    linesEl.querySelectorAll('.risk-time-toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const dsIndex = parseInt(btn.dataset.dsIndex, 10);
            if (riskChart?.data?.datasets?.[dsIndex]) {
                riskChart.data.datasets[dsIndex].hidden = !riskChart.data.datasets[dsIndex].hidden;
                riskChart.update('none');
                renderTimeModelLines(riskChart.data.datasets);
            }
        });
    });
}

async function updatePnlCurveAtIndex(dsIndex, legs, days, iv_shift) {
    if (!riskChart || !currentRiskChartPriceRange) return;
    try {
        const payload = { legs, days_to_add: days, iv_shift, price_range: currentRiskChartPriceRange };
        const res = await fetch(`${API_BASE_URL}/get_pnl_by_date`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (!res.ok) throw new Error('Curve fetch failed');
        const data = await res.json();
        const priceRange = currentRiskChartPriceRange || [];
        const mappedCurve = priceRange.map((price, i) => ({ x: parseNumber(price, 0), y: parseNumber(data.pnl_curve?.[i], 0) }));
        riskChart.data.datasets[dsIndex].data = mappedCurve;
        riskChart.data.datasets[dsIndex].label = `T+${days}`;
        riskChart.update('none');
        renderTimeModelLines(riskChart.data.datasets);
        const spot = parseNumber(currentRiskProfileData?.metrics?.current_und_price, 0);
        const spotIdx = getNearestIndexByValue(priceRange, spot);
        renderRiskCurvePanel(riskChart.data, spotIdx, getRiskReferenceCostBasis());
    } catch (e) { console.error('updatePnlCurveAtIndex failed:', e); }
}

// ========================================================================================
// --- RISK POSITION STRIP ---
// ========================================================================================
function renderRiskPositionStrip(legs, profileName) {
    const strip = document.getElementById('risk-position-strip');
    const tbody = document.getElementById('risk-pos-table-body');
    const nameLabel = document.getElementById('risk-pos-name-label');
    if (!strip || !tbody) return;

    if (!legs || legs.length === 0) { strip.classList.add('hidden'); return; }
    strip.classList.remove('hidden');

    if (nameLabel) {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
        const dateStr = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        nameLabel.textContent = `${escapeHtml(profileName || '—')} · Last Saved: ${dateStr}, ${timeStr}`;
    }

    let html = '';
    legs.forEach(leg => {
        const tws = portfolioData[leg.conId] || leg.tws_data;
        const contract = tws?.contract || {};
        const ticker = contract.symbol || '—';
        const secType = String(contract.secType || 'OPT').toUpperCase();
        const right = String(contract.right || '').toUpperCase();
        const typeLabel = secType === 'STK' ? 'STOCK' : (right === 'C' ? 'CALL' : right === 'P' ? 'PUT' : secType);
        const strike = parseNumber(contract.strike, 0);
        const qty = parseNumber(leg.qty, 0);
        const multiplier = tws ? getLegMultiplier(tws) : Math.max(1, parseNumber(leg.multiplier || 100, 100));
        const delta = tws ? parseNumber(tws.greeks?.delta, null) : null;
        const gamma = tws ? parseNumber(tws.greeks?.gamma, null) : null;
        const theta = tws ? parseNumber(tws.greeks?.theta, null) : null;
        const vega  = tws ? parseNumber(tws.greeks?.vega,  null) : null;
        const dailyPnl = tws ? parseNumber(tws.pnl?.daily, null) : null;
        const openPnl  = tws ? parseNumber(tws.pnl?.unrealized, null) : null;

        const netDelta = delta != null ? delta * qty * multiplier : null;
        const netGamma = gamma != null ? gamma * qty * multiplier : null;
        const netTheta = theta != null ? theta * qty * multiplier : null;
        const netVega  = vega  != null ? vega  * qty * multiplier : null;

        const qtyColor = qty >= 0 ? '#10b981' : '#f87171';
        const pnlColor = dailyPnl != null ? (dailyPnl >= 0 ? '#10b981' : '#f87171') : '';
        const openDesc = strike > 0
            ? `${contract.expiry ? String(contract.expiry).slice(2) : ''} ${strike}${right}`
            : formatCurrency(openPnl != null ? openPnl : leg.costBasis, true);

        html += `<tr>
            <td class="font-mono" title="${escapeHtml(contract.localSymbol || ticker)}">${escapeHtml(ticker)}</td>
            <td style="color:var(--text-muted)">${typeLabel}</td>
            <td class="tr font-mono">${escapeHtml(openDesc)}</td>
            <td class="tr">${netDelta != null ? formatNumber(netDelta, 0) : '—'}</td>
            <td class="tr">${netGamma != null ? formatNumber(netGamma, 1) : '—'}</td>
            <td class="tr" style="color:#f59e0b">${netTheta != null ? formatNumber(netTheta, 0) : '—'}</td>
            <td class="tr" style="color:#d946ef">${netVega != null ? formatNumber(netVega, 0) : '—'}</td>
            <td class="tr" style="color:${pnlColor}">${dailyPnl != null ? formatCurrency(dailyPnl, true) : '—'}</td>
        </tr>`;
    });
    tbody.innerHTML = html || '<tr><td colspan="8" class="text-center text-muted py-1.5">No live data.</td></tr>';

    // Wire tab buttons (clone to remove stale listeners)
    strip.querySelectorAll('.risk-pos-tab-btn').forEach(btn => {
        const newBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(newBtn, btn);
        newBtn.addEventListener('click', () => {
            const tab = newBtn.dataset.tab;
            strip.querySelectorAll('.risk-pos-tab-btn').forEach(b => b.classList.toggle('active', b === newBtn));
            const pv = document.getElementById('risk-pos-portfolio-view');
            const sv = document.getElementById('risk-pos-stats-view');
            if (pv) pv.classList.toggle('hidden', tab !== 'portfolio');
            if (sv) sv.classList.toggle('hidden', tab !== 'stats');
        });
    });

    // Stats tab: aggregate greeks
    const statsBody = document.getElementById('risk-pos-stats-body');
    if (statsBody) {
        let totD = 0, totG = 0, totT = 0, totV = 0, hasStats = false;
        legs.forEach(leg => {
            const tws = portfolioData[leg.conId] || leg.tws_data;
            const mult = tws ? getLegMultiplier(tws) : Math.max(1, parseNumber(leg.multiplier || 100, 100));
            const qty = parseNumber(leg.qty, 0);
            if (tws?.greeks) {
                totD += parseNumber(tws.greeks.delta, 0) * qty * mult;
                totG += parseNumber(tws.greeks.gamma, 0) * qty * mult;
                totT += parseNumber(tws.greeks.theta, 0) * qty * mult;
                totV += parseNumber(tws.greeks.vega,  0) * qty * mult;
                hasStats = true;
            }
        });
        statsBody.innerHTML = hasStats
            ? `<div class="grid grid-cols-2 gap-x-4 gap-y-0.5">
                <div>Δ Delta: <span class="text-primary">${formatNumber(totD, 0)}</span></div>
                <div>Γ Gamma: <span class="text-primary">${formatNumber(totG, 1)}</span></div>
                <div style="color:#f59e0b">Θ Theta: <span>${formatNumber(totT, 0)}</span></div>
                <div style="color:#d946ef">V Vega: <span>${formatNumber(totV, 0)}</span></div>
               </div>`
            : '<span class="text-muted">No live Greeks available.</span>';
    }
}

// ========================================================================================
// --- ADJUSTMENT COMPARE PANEL ---
// ========================================================================================
function updateAdjustmentComparePanel(price, dataPoints, basis) {
    const cursorRow = document.getElementById('risk-adjust-cursor-row');
    const compareEl = document.getElementById('risk-adjust-compare');
    const compareRows = document.getElementById('risk-adjust-compare-rows');
    const cursorPriceEl = document.getElementById('risk-adjust-cursor-price');

    if (!riskAdjustmentEnabled || !cursorRow || !compareEl || !compareRows) return;

    if (!price || !dataPoints || dataPoints.length === 0) {
        cursorRow.classList.add('hidden');
        compareEl.classList.add('hidden');
        return;
    }

    cursorRow.classList.remove('hidden');
    compareEl.classList.remove('hidden');
    if (cursorPriceEl) cursorPriceEl.textContent = `$${formatNumber(price, 2)}`;

    let rowsHtml = '';
    dataPoints.forEach(dp => {
        const dsLabel = dp.dataset?.label || '—';
        const val = parseNumber(dp.parsed?.y, 0);
        const color = dp.dataset?.borderColor || '#94a3b8';
        const valColor = val >= 0 ? '#10b981' : '#f87171';
        const pctStr = formatPercentFromBasis(val, basis);
        // BASE = current value; ADD placeholder shown as '—' (no adjustment added yet)
        rowsHtml += `<div class="risk-adjust-compare-row">
            <span style="background:${color}; width:8px; height:8px; border-radius:50%; display:inline-block; flex-shrink:0;"></span>
            <span class="truncate text-muted">${escapeHtml(dsLabel)}</span>
            <span class="text-right font-mono" style="color:${valColor}">${formatCurrency(val, true)}</span>
            <span class="text-right font-mono text-muted">—</span>
        </div>`;
    });
    compareRows.innerHTML = rowsHtml;
}

// ... (showRiskProfile, drawRiskChart remain mostly the same, ensuring formatters are called) ...
async function showRiskProfile({comboIndex, legs, name, sourceTab}) {
    let targetLegs = legs;
    let targetName = name;
    const resolvedSourceTab = sourceTab || (comboIndex != null ? 'combos' : 'builder');
    lastRiskSourceTab = resolvedSourceTab;

    currentRiskProfileLegs = null;
    currentRiskTableData = null;
    currentSgpvData = null;
    currentRiskAccountContext = null;
    sgpvNetLiqManualOverride = false;
    if (sgpvChart) { sgpvChart.destroy(); sgpvChart = null; }

    if (comboIndex != null) {
        const combo = customCombos[comboIndex]; if (!combo) return;
        targetName = combo.name;
        targetLegs = (combo.legs || []).filter(l => l.status === 'open').map(l => {
            const twsLeg = portfolioData[l.conId];
            const legCostBasis = getComboLegCostBasis(l, twsLeg);
            return { conId: l.conId, qty: l.qty, costBasis: legCostBasis };
        });
    }

    currentRiskProfileLegs = targetLegs;

    const riskPanel = document.getElementById('risk-panel');
    const closeBtn = document.getElementById('modal-close-btn');
    document.getElementById('modal-title').textContent = `Risk Profile: ${targetName}`;
    ensureChartPluginsRegistered();
    setRiskModalView('graph');
    activateTab(resolvedSourceTab);

    // Apply theme BEFORE showing modal content
    applyThemeToModal();

    if (closeBtn) closeBtn.textContent = 'Hide Risk Profile';
    if (riskPanel) {
        riskPanel.classList.remove('hidden');
        riskPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    enforceRiskModalLayout();
    const metricsEl = document.getElementById('key-metrics');
    metricsEl.innerHTML = `<div class="col-span-4 text-center text-muted">Loading...</div>`;
    renderRiskTableLoading();
    renderSgpvLoading();
    renderRiskChainContextUi(deriveRiskChainContext(targetLegs));
    renderRiskChainPlaceholder('Loading option chain...');
    renderRiskChainStatus('');
    syncSgpvAccountOptions(getSortedAccountsFromPortfolio());
    renderSgpvContextNote();
    clearRiskOverlayPanels();
    const chainPromise = loadRiskOptionChain(targetLegs);

    if (!targetLegs || targetLegs.length === 0) {
        metricsEl.innerHTML = `<div class="text-red-500 col-span-4">No open legs to profile.</div>`;
        if (riskChart) { riskChart.destroy(); riskChart = null; }
        destroyRiskStripCharts();
        document.getElementById('risk-chart-canvas').getContext('2d').clearRect(0,0,300,150);
        document.getElementById('aggregate-greeks').innerHTML = '';
        document.getElementById('aggregate-pnl').innerHTML = '';
        renderRiskTableLoading('No open legs to profile.');
        renderSgpvLoading('No open legs to profile.');
        renderSgpvContextNote();
        renderRiskChainContextUi(null);
        renderRiskChainPlaceholder('No open legs to profile.');
        renderRiskChainStatus('');
        return;
    }


    try {
        const res = await fetch(`${API_BASE_URL}/get_risk_profile`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({legs: targetLegs})});
        if (!res.ok) {
            let errorText = "Failed to fetch risk profile.";
            try { const err = await res.json(); errorText = err.error || errorText; } catch(e){}
            throw new Error(errorText);
        }
        const data = await res.json();

        currentRiskProfileData = data;
        currentRiskChartPriceRange = data.price_range;
        renderRiskLegsPanel(targetLegs);
        loadRiskTableData(targetLegs, data.metrics);
        await loadAccountRiskContext(targetLegs);
        loadSgpvData(targetLegs, data.metrics);
        drawRiskChart(); // Draw chart AFTER data is loaded
        updateKeyMetrics(data.metrics);
        setupInteractiveControls(targetLegs, data.metrics.days_to_expiry); // Setup AFTER data load
        updateAggregateGreeks(targetLegs);
        updateAggregatePnl(targetLegs);
        renderRiskPositionStrip(targetLegs, targetName);

    } catch (e) {
        document.getElementById('risk-chart-canvas').getContext('2d').clearRect(0,0,300,150);
        metricsEl.innerHTML = `<div class="text-red-600 dark:text-red-400 col-span-4 p-4 text-center">${e.message}</div>`; // Adjusted colors
        console.error(e);
        destroyRiskStripCharts();
        currentRiskTableData = null;
        currentSgpvData = null;
        currentRiskAccountContext = null;
        if (sgpvChart) { sgpvChart.destroy(); sgpvChart = null; }
        renderRiskTableLoading(e.message);
        renderSgpvLoading(e.message);
        renderSgpvContextNote();
        if (riskChart) { riskChart.destroy(); riskChart = null; }
        clearRiskOverlayPanels();
    }
    await chainPromise;
}


function drawRiskChart() {
    if (!currentRiskProfileData) return;
    const data = currentRiskProfileData;
    if (riskChart) riskChart.destroy();
    const ctx = document.getElementById('risk-chart-canvas').getContext('2d');
    const css = getComputedStyle(document.documentElement);
    const colors = {
        t0: '#f87171',    // coral/red — most active curve
        exp: '#e2e8f0',   // near-white for expiry
        t1: '#fbbf24',    // amber
        t2: '#34d399',    // emerald
        t3: '#60a5fa',    // sky blue
        t4: '#c084fc',    // purple
        text: css.getPropertyValue('--text-primary').trim(),
        textMuted: css.getPropertyValue('--text-muted').trim(),
        zeroLine: css.getPropertyValue('--text-muted').trim(),
        grid: css.getPropertyValue('--border-color').trim(),
        spotLine: css.getPropertyValue('--button-primary-bg').trim(),
        breakevenLine: css.getPropertyValue('--text-muted').trim(),
        breakevenLabelBg: css.getPropertyValue('--bg-tertiary').trim(),
        tooltipBg: css.getPropertyValue('--bg-secondary').trim(),
        tooltipBorder: css.getPropertyValue('--border-color').trim(),
    };

    const timeSteps = data.metrics.time_steps || [];
    const intermediateCurves = data.intermediate_curves ? Object.keys(data.intermediate_curves) : [];
    const priceRange = data.price_range || [];
    const toSeries = (curve) => priceRange.map((price, index) => ({
        x: parseNumber(price, 0),
        y: parseNumber(curve?.[index], 0),
    }));

    const datasets = [{
        label: 'T+0',
        data: toSeries(data.t0_pnl_curve),
        borderColor: colors.t0,
        borderWidth: 2.8,
        pointRadius: 0,
        tension: 0.24,
        fill: { target: 'origin', above: 'rgba(248, 113, 113, 0.10)', below: 'rgba(248, 113, 113, 0.06)' }
    }];
    const interColors = [colors.t1, colors.t2, colors.t3, colors.t4];
    intermediateCurves.forEach((key, index) => {
        if (index < timeSteps.length) {
            datasets.push({
                label: `T+${timeSteps[index]}`,
                data: toSeries(data.intermediate_curves[key]),
                borderColor: interColors[index % interColors.length],
                borderWidth: 1.7,
                pointRadius: 0,
                tension: 0.24,
                borderDash: []
            });
        }
    });
    datasets.push({
        label: `Expiry T+${data.metrics.days_to_expiry}`,
        data: toSeries(data.exp_pnl_curve),
        borderColor: colors.exp,
        borderWidth: 2.6,
        pointRadius: 0,
        tension: 0.22
    });

    const allY = datasets.flatMap((d) => d.data || []).map((v) => parseNumber(v?.y, 0));
    const minY = Math.min(...allY, 0);
    const maxY = Math.max(...allY, 0);
    const yPadding = Math.max((maxY - minY) * 0.12, 200);
    const yMin = minY - yPadding;
    const yMax = maxY + yPadding;

    const spot = parseNumber(data.metrics.current_und_price, 0);
    const basis = getRiskReferenceCostBasis();
    const spotIdx = getNearestIndexByValue(priceRange, spot);

    const annotations = {
        zero: {
            type: 'line',
            yMin: 0,
            yMax: 0,
            borderColor: colors.zeroLine,
            borderWidth: 1.2,
            borderDash: [5, 5],
            scaleID: 'y'
        },
        spotBand: {
            type: 'box',
            xMin: spot * 0.9,
            xMax: spot * 1.1,
            yMin,
            yMax,
            backgroundColor: 'rgba(148, 163, 184, 0.08)',
            borderWidth: 0
        },
        spot: {
            type: 'line',
            scaleID: 'x',
            value: spot,
            borderColor: colors.spotLine,
            borderWidth: 1.9,
            borderDash: [6, 5],
            label: {
                enabled: true,
                content: `ATM ${formatNumber(spot, 2)}`,
                position: 'start',
                yAdjust: -14,
                backgroundColor: colors.spotLine,
                color: '#ffffff',
                font: { size: 10, weight: '700' },
                padding: { top: 4, bottom: 4, left: 6, right: 6 },
                borderRadius: 6
            }
        }
    };
    (data.metrics.breakevens_exp || []).forEach((be, i) => {
        if (priceRange.length > 0 && be >= priceRange[0] && be <= priceRange[priceRange.length - 1]) {
            annotations[`be${i}`] = {
                type: 'line',
                scaleID: 'x',
                value: be,
                borderColor: colors.breakevenLine,
                borderWidth: 1,
                borderDash: [2, 4],
                label: {
                    enabled: true,
                    content: `BE ${formatNumber(be, 2)}`,
                    position: 'end',
                    yAdjust: 16,
                    backgroundColor: colors.breakevenLabelBg,
                    color: colors.text,
                    font: { size: 9, weight: '600' },
                    padding: 3,
                    borderRadius: 4
                }
            };
        }
    });

    const externalTooltipHandler = ({chart, tooltip}) => {
        const el = document.getElementById('chart-tooltip');
        if (!el) return;
        el.style.background = colors.tooltipBg;
        el.style.color = colors.text;
        el.style.borderColor = colors.tooltipBorder;
        if (tooltip.opacity === 0) {
            el.style.opacity = 0;
            updateRiskCrosshair(spot);
            setRiskCursorChips(null, null, null);
            updateAdjustmentComparePanel(null, null, null);
            return;
        }

        const price = parseNumber(tooltip.dataPoints?.[0]?.parsed?.x, 0);
        const pctFromSpot = spot ? ((price - spot) / spot) * 100 : 0;
        const nearestIdx = getNearestIndexByValue(priceRange, price);
        const gDelta = parseNumber(data.greek_curves?.delta?.[nearestIdx], NaN);
        const gGamma = parseNumber(data.greek_curves?.gamma?.[nearestIdx], NaN);
        const gTheta = parseNumber(data.greek_curves?.theta?.[nearestIdx], NaN);
        const gVega = parseNumber(data.greek_curves?.vega?.[nearestIdx], NaN);
        let innerHtml = `<div class="font-semibold text-center mb-1 border-b pb-1" style="border-color: ${colors.grid};">Stock Price: $${formatNumber(price, 2)} (${pctFromSpot >= 0 ? '+' : ''}${pctFromSpot.toFixed(2)}%)</div><table>`;
        tooltip.body.forEach((item, i) => {
            const labelColors = tooltip.labelColors[i];
            const style = `background:${labelColors.borderColor}; border-radius:2px; display:inline-block; height:10px; width:10px; margin-right:6px;`;
            const label = tooltip.dataPoints?.[i]?.dataset?.label || item.lines[0] || 'Curve';
            const val = parseNumber(tooltip.dataPoints?.[i]?.parsed?.y, 0);
            innerHtml += `<tr><td><span style="${style}"></span> ${label}</td><td class="text-right font-medium pl-2">${formatCurrency(val, true)} <span class="text-muted">${formatPercentFromBasis(val, basis)}</span></td></tr>`;
        });
        innerHtml += `
            <tr><td colspan="2"><div class="mt-2 border-t pt-2 text-[11px] text-muted" style="border-color:${colors.grid};">Greeks (T+0)</div></td></tr>
            <tr><td>Δ Delta</td><td class="text-right font-medium">${Number.isFinite(gDelta) ? formatNumber(gDelta, 0) : '—'}</td></tr>
            <tr><td>Γ Gamma</td><td class="text-right font-medium">${Number.isFinite(gGamma) ? formatNumber(gGamma, 0) : '—'}</td></tr>
            <tr><td>Θ Theta</td><td class="text-right font-medium">${Number.isFinite(gTheta) ? formatNumber(gTheta, 0) : '—'}</td></tr>
            <tr><td>V Vega</td><td class="text-right font-medium">${Number.isFinite(gVega) ? formatNumber(gVega, 0) : '—'}</td></tr>
        `;
        el.innerHTML = innerHtml + '</table>';
        updateRiskCrosshair(price);
        setRiskCursorChips(price, tooltip.dataPoints || [], basis);
        updateAdjustmentComparePanel(price, tooltip.dataPoints || [], basis);

        const { offsetLeft: pX, offsetTop: pY } = chart.canvas;
        el.style.opacity = 1;
        let left = pX + tooltip.caretX + 15;
        if (left + el.offsetWidth + pX > chart.width + pX) left = pX + tooltip.caretX - el.offsetWidth - 15;
        if (left < pX) left = pX + 5;
        el.style.left = left + 'px';
        el.style.top = pY + tooltip.caretY - (el.offsetHeight / 2) + 'px';
    };

    riskChart = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: Math.max(window.devicePixelRatio || 1, 2),
            interaction: { mode: 'index', intersect: false },
            animation: { duration: 220 },
            layout: { padding: { top: 22, right: 8, bottom: 6, left: 8 } },
            plugins: {
                title: {
                    display: true,
                    text: 'Modeled Portfolio Exposure',
                    color: colors.text,
                    font: { family: "'Space Grotesk', sans-serif", size: 28, weight: '700' },
                    padding: { top: 8, bottom: 10 }
                },
                legend: {
                    position: 'bottom',
                    labels: {
                        color: colors.text,
                        usePointStyle: true,
                        boxWidth: 8,
                        boxHeight: 8,
                        padding: 14,
                        font: { family: "'IBM Plex Mono', monospace", size: 11, weight: '600' }
                    }
                },
                tooltip: { enabled: false, external: externalTooltipHandler, position: 'nearest' },
                annotation: { annotations },
                zoom: {
                    pan: { enabled: true, mode: 'x' },
                    zoom: { drag: { enabled: true }, wheel: { enabled: false }, pinch: { enabled: false }, mode: 'x' }
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'Underlying Price ($)', color: colors.text },
                    grid: { color: `${colors.grid}66` },
                    ticks: {
                        color: colors.text,
                        maxTicksLimit: 9,
                        maxRotation: 0,
                        autoSkipPadding: 18,
                        callback(value) {
                            const priceAtTick = parseNumber(value, NaN);
                            return Number.isFinite(priceAtTick) ? `$${formatNumber(priceAtTick, 0)}` : '';
                        }
                    }
                },
                xTop: {
                    type: 'linear',
                    position: 'top',
                    min: priceRange[0],
                    max: priceRange[priceRange.length - 1],
                    title: { display: true, text: 'Delta vs Spot', color: colors.textMuted },
                    grid: { display: false },
                    ticks: {
                        color: colors.textMuted,
                        maxTicksLimit: 7,
                        callback(value) {
                            const priceAtTick = parseNumber(value, NaN);
                            if (!Number.isFinite(priceAtTick) || !spot) return '';
                            const pct = ((priceAtTick - spot) / spot) * 100;
                            return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
                        }
                    }
                },
                y: {
                    title: { display: true, text: 'P&L ($)', color: colors.text },
                    min: yMin,
                    max: yMax,
                    grid: { color: `${colors.grid}88` },
                    ticks: { color: colors.text, maxTicksLimit: 8, callback: (value) => formatAxisCurrency(value) }
                },
                yPct: {
                    position: 'right',
                    min: yMin,
                    max: yMax,
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: 'P&L (%)', color: colors.textMuted },
                    ticks: {
                        color: colors.textMuted,
                        callback: (value) => formatPercentFromBasis(value, basis)
                    }
                }
            }
        }
    });

    renderRiskCurvePanel(riskChart.data, spotIdx, basis);
    renderRiskLegsPanel(currentRiskProfileLegs);
    drawRiskStripCharts(priceRange, data.greek_curves, data.t0_pnl_curve, spot);
    updateRiskCrosshair(spot);
    renderTimeModelLines(riskChart.data.datasets);
}


// ... (updateKeyMetrics remains mostly the same, using formatters) ...
function updateKeyMetrics(m) {
    const metricsEl = document.getElementById('key-metrics');
    if (!metricsEl) return;
    metricsEl.innerHTML = `
        <div><div class="text-xs text-muted">Und. Price</div><div class="font-semibold text-primary">$${formatNumber(m.current_und_price)}</div></div>
        <div><div class="text-xs text-muted">Max Profit</div><div class="font-semibold">${formatCurrency(m.max_profit)}</div></div>
        <div><div class="text-xs text-muted">Max Loss</div><div class="font-semibold">${formatCurrency(m.max_loss, true)}</div></div>
        <div><div class="text-xs text-muted">Breakevens</div><div class="text-sm font-semibold text-primary">${(m.breakevens_exp || []).join(', ')||'N/A'}</div></div>`;
}


function setupInteractiveControls(legs, dte) {
    const ds = document.getElementById('date-slider'), dl = document.getElementById('date-slider-label');
    const is = document.getElementById('iv-slider'), il = document.getElementById('iv-slider-label');
    const ivEnabledInput = document.getElementById('risk-iv-enabled');
    const timeEnabledInput = document.getElementById('risk-time-enabled');
    const adjustEnabledInput = document.getElementById('risk-adjust-enabled');
    const adjustNote = document.getElementById('risk-adjust-note');
    const ivResetBtn = document.getElementById('iv-reset-btn');

    if (ds) { ds.max = dte > 0 ? dte : 1; ds.value = 0; }
    if (dl) dl.textContent = 'T+0';
    if (is) is.value = 0;
    if (il) il.textContent = '+0%';
    riskIvEnabled = true; riskTimeEnabled = true; riskAdjustmentEnabled = false;
    if (ivEnabledInput) ivEnabledInput.checked = true;
    if (timeEnabledInput) timeEnabledInput.checked = true;
    if (adjustEnabledInput) adjustEnabledInput.checked = false;
    if (is) is.disabled = false;

    // IV slider handler — re-fetches first T+N curve with new IV
    const ivHandler = () => {
        const days = riskTimeEnabled ? parseInt(ds?.value || 0) : 0;
        const ivShift = riskIvEnabled ? (parseInt(is?.value || 0) / 100.0) : 0;
        if (il) il.textContent = `${(is?.value ?? 0) >= 0 ? '+' : ''}${is?.value ?? 0}%`;
        updatePnlCurve(legs, days, ivShift);
    };
    if (is) is.oninput = ivHandler;

    if (ivEnabledInput) {
        const newInput = ivEnabledInput.cloneNode(true);
        ivEnabledInput.parentNode.replaceChild(newInput, ivEnabledInput);
        newInput.onchange = () => {
            riskIvEnabled = !!newInput.checked;
            if (is) is.disabled = !riskIvEnabled;
            if (!riskIvEnabled && is) { is.value = 0; if (il) il.textContent = '+0%'; }
            ivHandler();
        };
    }

    // Time toggle — hide/show all intermediate datasets
    if (timeEnabledInput) {
        const newTInput = timeEnabledInput.cloneNode(true);
        timeEnabledInput.parentNode.replaceChild(newTInput, timeEnabledInput);
        newTInput.onchange = () => {
            riskTimeEnabled = !!newTInput.checked;
            if (riskChart?.data?.datasets) {
                riskChart.data.datasets.forEach((d, idx) => {
                    const lbl = String(d.label || '');
                    if (lbl !== 'T+0' && !lbl.startsWith('Expiry')) {
                        d.hidden = !riskTimeEnabled;
                    }
                });
                riskChart.update('none');
                renderTimeModelLines(riskChart.data.datasets);
            }
        };
    }

    // Adjustment toggle
    if (adjustEnabledInput) {
        const newAInput = adjustEnabledInput.cloneNode(true);
        adjustEnabledInput.parentNode.replaceChild(newAInput, adjustEnabledInput);
        newAInput.onchange = () => {
            riskAdjustmentEnabled = !!newAInput.checked;
            const cursorRow = document.getElementById('risk-adjust-cursor-row');
            const compareEl = document.getElementById('risk-adjust-compare');
            if (!riskAdjustmentEnabled) {
                if (cursorRow) cursorRow.classList.add('hidden');
                if (compareEl) compareEl.classList.add('hidden');
            }
            if (adjustNote) adjustNote.textContent = riskAdjustmentEnabled
                ? 'Adjustment mode on. Move cursor over chart to compare curves.'
                : 'Toggle to compare overlaid adjustment curves vs baseline.';
        };
    }

    // Clear All button for adjustment panel
    const adjustClearBtn = document.getElementById('risk-adjust-clear-btn');
    if (adjustClearBtn) {
        const newClearBtn = adjustClearBtn.cloneNode(true);
        adjustClearBtn.parentNode.replaceChild(newClearBtn, adjustClearBtn);
        newClearBtn.onclick = () => {
            const compareEl = document.getElementById('risk-adjust-compare');
            const cursorRow = document.getElementById('risk-adjust-cursor-row');
            if (compareEl) compareEl.classList.add('hidden');
            if (cursorRow) cursorRow.classList.add('hidden');
        };
    }

    if (ivResetBtn) {
        const newIvResetBtn = ivResetBtn.cloneNode(true);
        ivResetBtn.parentNode.replaceChild(newIvResetBtn, ivResetBtn);
        newIvResetBtn.onclick = () => { if (is) { is.value = 0; ivHandler(); } };
    }

    const resetButton = document.getElementById('reset-zoom-btn');
    if (resetButton) {
        const newResetButton = resetButton.cloneNode(true);
        resetButton.parentNode.replaceChild(newResetButton, resetButton);
        newResetButton.addEventListener('click', () => {
            try { if (riskChart?.resetZoom) riskChart.resetZoom('none'); }
            catch(e) { console.error('Error resetting zoom:', e); }
        });
    }

    // Populate time model lines from current chart
    if (riskChart?.data?.datasets) {
        renderTimeModelLines(riskChart.data.datasets);
    }
}


// ... (updatePnlCurve, updateAggregateGreeks, updateAggregatePnl remain the same) ...
async function updatePnlCurve(legs, days, iv_shift) {
    if(!riskChart || !currentRiskChartPriceRange) return;
    try {
        const payload = { legs, days_to_add: days, iv_shift, price_range: currentRiskChartPriceRange };
        const res = await fetch(`${API_BASE_URL}/get_pnl_by_date`,{ method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
        if (!res.ok) throw new Error('Failed to update curve');
        const data = await res.json();
        let targetDatasetIndex = riskChart.data.datasets.findIndex((ds) => /^T\+\d+$/.test(ds.label || '') && ds.label !== 'T+0');
        if (targetDatasetIndex === -1) {
            targetDatasetIndex = riskChart.data.datasets.findIndex((ds) => String(ds.label || '').startsWith('T+'));
        }
        if (targetDatasetIndex !== -1) {
            const mappedCurve = (currentRiskChartPriceRange || []).map((price, index) => ({
                x: parseNumber(price, 0),
                y: parseNumber(data.pnl_curve?.[index], 0),
            }));
            riskChart.data.datasets[targetDatasetIndex].data = mappedCurve;
            riskChart.data.datasets[targetDatasetIndex].label = `T+${days}`;
            riskChart.update('none');
            const spot = parseNumber(currentRiskProfileData?.metrics?.current_und_price, 0);
            const spotIdx = getNearestIndexByValue(currentRiskChartPriceRange, spot);
            if (data.greek_curves && currentRiskProfileData) {
                currentRiskProfileData.greek_curves = data.greek_curves;
            }
            renderRiskCurvePanel(riskChart.data, spotIdx, getRiskReferenceCostBasis());
            drawRiskStripCharts(
                currentRiskChartPriceRange || [],
                currentRiskProfileData?.greek_curves || {},
                data.pnl_curve,
                currentRiskCrosshairPrice ?? spot
            );
            updateRiskCrosshair(currentRiskCrosshairPrice ?? spot);
            renderTimeModelLines(riskChart.data.datasets);
        } else { console.warn("Could not find T+N dataset to update."); }
    } catch(e) { console.error("Curve update failed:", e); }
}

function updateAggregateGreeks(legs) {
    const g={delta:0,gamma:0,vega:0,theta:0};
    let usedLiveGreeks = false;
    (legs || []).forEach(leg => {
        const tws = leg.tws_data || portfolioData[leg.conId];
        if(tws && (tws.status?.startsWith('Live') || tws.status === 'Snapshot')){
            const m = parseFloat(tws.contract?.multiplier || 100);
            g.delta += (tws.greeks?.delta||0) * leg.qty * m;
            g.gamma += (tws.greeks?.gamma||0) * leg.qty * m;
            g.vega  += (tws.greeks?.vega||0) * leg.qty * m;
            g.theta += (tws.greeks?.theta||0) * leg.qty * m;
            usedLiveGreeks = true;
        }
    });
    if (!usedLiveGreeks && currentRiskProfileData && Array.isArray(currentRiskChartPriceRange) && currentRiskChartPriceRange.length) {
        const spot = parseNumber(currentRiskProfileData?.metrics?.current_und_price, 0);
        const idx = getNearestIndexByValue(currentRiskChartPriceRange, spot);
        g.delta = parseNumber(currentRiskProfileData?.greek_curves?.delta?.[idx], 0);
        g.gamma = parseNumber(currentRiskProfileData?.greek_curves?.gamma?.[idx], 0);
        g.vega = parseNumber(currentRiskProfileData?.greek_curves?.vega?.[idx], 0);
        g.theta = parseNumber(currentRiskProfileData?.greek_curves?.theta?.[idx], 0);
    }
    const greeksEl = document.getElementById('aggregate-greeks');
    if (greeksEl) {
        greeksEl.innerHTML = `<div><span class="font-semibold">Net Δ:</span> ${coloredGreek(g.delta)}</div><div><span class="font-semibold">Net Γ:</span> ${coloredGreek(g.gamma)}</div><div><span class="font-semibold">Net ν:</span> ${coloredGreek(g.vega)}</div><div><span class="font-semibold">Net θ:</span> ${coloredGreek(g.theta)}</div>`;
    }
}

function updateAggregatePnl(legs) {
    const pnlEl = document.getElementById('aggregate-pnl');
    if (!pnlEl) return;
    let totalPnl = 0, dailyPnl = 0, totalCostBasis = 0, usedLivePnl = false;
    (legs || []).forEach(leg => {
        const twsLeg = leg.tws_data || portfolioData[leg.conId];
        if (twsLeg) {
             const legCostBasis = leg.costBasis || 0;
             totalCostBasis += legCostBasis;
             const ratio = twsLeg.position !== 0 ? leg.qty / twsLeg.position : 0;
             totalPnl += (twsLeg.marketValue * ratio) - legCostBasis;
             dailyPnl += (twsLeg.pnl?.daily || 0) * ratio;
             usedLivePnl = true;
        }
    });
    if (!usedLivePnl && currentRiskProfileData && Array.isArray(currentRiskChartPriceRange) && currentRiskChartPriceRange.length) {
        const spot = parseNumber(currentRiskProfileData?.metrics?.current_und_price, 0);
        const idx = getNearestIndexByValue(currentRiskChartPriceRange, spot);
        totalPnl = parseNumber(currentRiskProfileData?.t0_pnl_curve?.[idx], 0);
        totalCostBasis = getRiskReferenceCostBasis();
        dailyPnl = 0;
    }
    pnlEl.innerHTML = `
        <div><span class="font-semibold">Total P&L:</span> ${formatPnlWithPercent(totalPnl, totalCostBasis)}</div>
        <div><span class="font-semibold">Daily P&L:</span> ${formatPnlWithPercent(dailyPnl, totalCostBasis)}</div>`;
}

// --- Theme Switching Logic ---

function applyInitialTheme() {
    const themeCheckbox = document.getElementById('global-theme-checkbox');
    const useLightMode = themeCheckbox ? themeCheckbox.checked : false; // Default dark
    setTheme(useLightMode); // Apply the theme
}

function toggleTheme() {
    const isLightMode = document.getElementById('global-theme-checkbox')?.checked;
    setTheme(isLightMode); // Set theme based on checkbox
}

// Central function to set the theme
function setTheme(isLightMode) {
     const themeCheckbox = document.getElementById('global-theme-checkbox');
     if (isLightMode) {
        document.body.classList.add('light-mode');
        document.body.classList.remove('dark-mode');
        if (themeCheckbox && !themeCheckbox.checked) themeCheckbox.checked = true; // Sync checkbox
    } else {
        document.body.classList.remove('light-mode');
        document.body.classList.add('dark-mode');
        if (themeCheckbox && themeCheckbox.checked) themeCheckbox.checked = false; // Sync checkbox
    }
    // Update elements after setting body class
    applyThemeToElements();
    applyThemeToModal(); // Important for modal consistency
}


function applyThemeToElements() {
    // Re-rendering tables is necessary if colors depend on row index etc.
    // If colors only depend on +/- values, formatters handle it. Let's try without full redraw first.
    // Re-render might be needed if backgrounds change (e.g., bg-tertiary/30)
    renderLegsTable(); // Redraw needed due to bg/text color changes
    updateCombosView(true); // Redraw needed due to bg/text color changes
    updateStatusBanner();

    // Update chart if it exists and modal is potentially open
    applyThemeToModal();
}


function applyThemeToModal() {
    const modal = document.getElementById('risk-panel');
    // Only proceed if modal exists and potentially visible (or about to be)
    if (!modal) return;

    const isLightMode = document.body.classList.contains('light-mode'); // Check body class
    const modalContent = document.getElementById('risk-modal-content');

    // Add/remove a simple class to the modal content itself
    if (modalContent) {
        if (isLightMode) {
            modalContent.classList.add('light-mode'); // Use class for scoping modal styles
             modalContent.classList.remove('dark-mode');
        } else {
            modalContent.classList.add('dark-mode');
             modalContent.classList.remove('light-mode');
        }
    }

    // Redraw chart and update metrics IF the modal is currently visible
    if (!modal.classList.contains('hidden')) {
        if (currentRiskProfileData && riskChart) {
            drawRiskChart(); // Redraws chart with new theme colors
            updateKeyMetrics(currentRiskProfileData.metrics); // Updates metrics text/colors
            updateAggregateGreeks(currentRiskProfileLegs); // Updates greeks text/colors
            updateAggregatePnl(currentRiskProfileLegs); // Updates PnL text/colors
        } else if (currentRiskProfileData) {
             // Data exists but chart doesn't (maybe first open), just update metrics/greeks/pnl
             updateKeyMetrics(currentRiskProfileData.metrics);
             updateAggregateGreeks(currentRiskProfileLegs);
             updateAggregatePnl(currentRiskProfileLegs);
        }
        if (currentSgpvData) {
            renderSgpvSummary();
            renderSgpvContextNote();
            drawSgpvChart();
        }
    }
}
