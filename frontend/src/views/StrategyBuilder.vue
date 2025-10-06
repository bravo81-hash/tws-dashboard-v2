<script setup>
import { ref, watch, computed } from 'vue';
import OptionChainTable from '@/components/OptionChainTable.vue';
import RiskProfileChart from '@/components/RiskProfileChart.vue';
// Import both mock data objects
import { mockOptionChain, mockTickerAnalytics } from '@/mockData.js';
import { formatGreek, formatCurrency, formatNumber } from '@/utils/formatters.js';

// --- Configuration ---
const useMockData = false; // <-- Re-enabled mock mode

// ... (all state refs are the same) ...
const symbol = ref('SPY'); // Set default for mock mode
const selectedExpiry = ref('');
const chain = ref([]);
const undPrice = ref(0);
const isLoading = ref(false);
const error = ref(null);
const strategyLegs = ref([]);
const isProfileVisible = ref(false);
const isProfileLoading = ref(false);
const profileData = ref(null);
const profileError = ref(null);
const strategyName = ref('');
const ivRank = ref(null);
const ivPercentile = ref(null);
const analyticsExpiries = ref([]);

// ... (formatExpiryDate helper is the same) ...
function formatExpiryDate(yyyymmdd, dte, expectedMove) { const year = parseInt(yyyymmdd.substring(0, 4), 10); const month = parseInt(yyyymmdd.substring(4, 6), 10) - 1; const day = parseInt(yyyymmdd.substring(6, 8), 10); const expiryDate = new Date(Date.UTC(year, month, day)); const today = new Date(); const todayUTC = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())); const dteCalc = Math.round((expiryDate - todayUTC) / (1000 * 60 * 60 * 24)); const formattedDate = expiryDate.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }).replace(/ /g, '-').toUpperCase(); return { value: yyyymmdd, text: `${formattedDate} (${dte} DTE) ~ Exp Move: ±${formatCurrency(expectedMove)}` }; }

// ... (computed properties are the same) ...
const formattedExpiries = computed(() => { return analyticsExpiries.value.map(exp => formatExpiryDate(exp.expiry, exp.dte, exp.expected_move)); });
const strategyGreeks = computed(() => { const totals = { delta: 0, gamma: 0, vega: 0, theta: 0 }; if (strategyLegs.value.length === 0) return totals; for (const leg of strategyLegs.value) { const multiplier = 100; const legGreeks = leg.data; if (legGreeks) { totals.delta += (legGreeks.delta || 0) * leg.quantity * multiplier; totals.gamma += (legGreeks.gamma || 0) * leg.quantity * multiplier; totals.vega += (legGreeks.vega || 0) * leg.quantity * multiplier; totals.theta += (legGreeks.theta || 0) * leg.quantity * multiplier; } } return totals; });
const strategyDebitCredit = computed(() => { if (strategyLegs.value.length === 0) return 0; let totalCost = 0; for (const leg of strategyLegs.value) { const legData = leg.data; if (legData) { const price = leg.quantity > 0 ? legData.ask : legData.bid; totalCost += (price || 0) * leg.quantity * 100; } } return totalCost; });

// --- UPDATED: loadAnalytics now handles mock data ---
async function loadAnalytics() {
  isLoading.value = true;
  error.value = null;
  analyticsExpiries.value = [];
  selectedExpiry.value = '';
  chain.value = [];
  strategyLegs.value = [];
  ivRank.value = null;
  ivPercentile.value = null;

  if (useMockData) {
    console.log("--- Using Mock Analytics Data ---");
    await new Promise(resolve => setTimeout(resolve, 500)); // Simulate delay
    const data = mockTickerAnalytics;
    ivRank.value = data.iv_rank;
    ivPercentile.value = data.iv_percentile;
    analyticsExpiries.value = data.expiries;
    if (analyticsExpiries.value.length > 0) {
      selectedExpiry.value = analyticsExpiries.value[0].expiry;
    }
    isLoading.value = false;
    return;
  }
  
  // This part only runs if useMockData is false
  if (!symbol.value) {
      isLoading.value = false;
      return;
  };

  try {
    const response = await fetch(`http://127.0.0.1:8000/options/analytics?symbol=${symbol.value.toUpperCase()}`);
    if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to load analytics.');
    }
    const data = await response.json();
    
    ivRank.value = data.iv_rank;
    ivPercentile.value = data.iv_percentile;
    analyticsExpiries.value = data.expiries;

    if (analyticsExpiries.value.length > 0) {
      selectedExpiry.value = analyticsExpiries.value[0].expiry;
    }
  } catch (e) {
    error.value = e.message;
  } finally {
    isLoading.value = false;
  }
}

// ... (rest of the script is unchanged) ...
async function saveStrategy() { if (!strategyName.value) { alert('Please enter a name for the strategy.'); return; } if (strategyLegs.value.length === 0) { alert('Cannot save an empty strategy.'); return; } const payload = { name: strategyName.value, ticker: symbol.value.toUpperCase(), legs: strategyLegs.value, cost_basis: strategyDebitCredit.value }; try { const response = await fetch('http://127.0.0.1:8000/strategies/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), }); if (!response.ok) { const err = await response.json(); throw new Error(err.detail || 'Failed to save strategy.'); } alert(`Strategy '${strategyName.value}' saved successfully!`); strategyName.value = ''; } catch (e) { alert(e.message); console.error('Failed to save strategy:', e); } }
async function loadChain() { if (!symbol.value || !selectedExpiry.value) return; isLoading.value = true; error.value = null; chain.value = []; try { let data; if (useMockData) { console.log("--- Using Mock Data ---"); await new Promise(resolve => setTimeout(resolve, 500)); data = mockOptionChain; } else { console.log("--- Fetching Live Data ---"); const response = await fetch(`http://127.0.0.1:8000/options/chain?symbol=${symbol.value.toUpperCase()}&expiry=${selectedExpiry.value}`); if (!response.ok) { const errData = await response.json(); throw new Error(errData.detail || 'Failed to load option chain.'); } data = await response.json(); } chain.value = data.chain; undPrice.value = data.undPrice; } catch (e) { error.value = e.message; } finally { isLoading.value = false; } }
watch(selectedExpiry, (newExpiry) => { if (newExpiry) { strategyLegs.value = []; loadChain(); } });
function handleAddLeg(legData) { const { optionData, side } = legData; const newLeg = { contract: optionData.contract, data: optionData.data, side: side, id: Date.now(), quantity: side === 'Buy' ? 1 : -1, }; strategyLegs.value.push(newLeg); }
function removeLeg(legId) { strategyLegs.value = strategyLegs.value.filter(leg => leg.id !== legId); }
async function showProfile() { if (strategyLegs.value.length === 0) return; isProfileVisible.value = true; isProfileLoading.value = true; profileError.value = null; profileData.value = null; const requestLegs = strategyLegs.value.map(leg => ({ quantity: leg.quantity, strike: leg.contract.strike, right: leg.contract.right.toLowerCase(), expiry: leg.contract.lastTradeDateOrContractMonth, iv: leg.data.iv, })); const payload = { legs: requestLegs, undPrice: undPrice.value, }; try { const response = await fetch('http://127.0.0.1:8000/options/calculate-profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), }); if (!response.ok) { const err = await response.json(); throw new Error(err.detail || 'Failed to calculate profile'); } profileData.value = await response.json(); } catch (e) { profileError.value = e.message; console.error("Profile calculation error:", e); } finally { isProfileLoading.value = false; } }
// Automatically load analytics in mock mode
if (useMockData) { loadAnalytics(); }
</script>

<template>
  <div class="space-y-6"><div class="bg-secondary text-secondary-foreground rounded-lg shadow-lg p-6"><h2 class="text-2xl font-bold mb-4">Strategy Builder</h2><div class="flex items-end space-x-4"><div class="flex-shrink-0"><label class="text-xs text-foreground/70">Symbol</label><input v-model="symbol" @keyup.enter="loadAnalytics" type="text" placeholder="e.g., SPY" class="bg-background text-foreground rounded-md px-4 py-2 border border-border w-40 mt-1"/></div><button @click="loadAnalytics" class="bg-accent hover:bg-accent/90 text-accent-foreground font-bold py-2 px-4 rounded-md">Load Analytics</button><div v-if="formattedExpiries.length > 0" class="flex-shrink-0"><label class="text-xs text-foreground/70">Expiry Date</label><select v-model="selectedExpiry" class="bg-background text-foreground rounded-md px-4 py-2 border border-border w-72 mt-1"><option disabled value="">Select an expiry</option><option v-for="exp in formattedExpiries" :key="exp.value" :value="exp.value">{{ exp.text }}</option></select></div></div><div v-if="ivRank !== null" class="mt-4 flex items-center space-x-6 text-sm font-mono p-3 bg-background/50 rounded-md"><div><span class="text-foreground/70">IV Rank: </span><span class="font-semibold">{{ formatNumber(ivRank, 1) }}%</span></div><div><span class="text-foreground/70">IV Percentile: </span><span class="font-semibold">{{ formatNumber(ivPercentile, 1) }}%</span></div></div></div><div v-if="strategyLegs.length > 0" class="bg-secondary text-secondary-foreground rounded-lg shadow-lg p-6"><div class="flex justify-between items-center mb-4"><h3 class="text-xl font-bold">Theoretical Strategy</h3><div class="flex items-center space-x-4 text-sm font-mono"><div class="flex items-center space-x-1 p-2 bg-background/50 rounded-md"><span class="text-foreground/70">{{ strategyDebitCredit <= 0 ? 'Credit' : 'Debit' }}</span><span class="font-semibold" :class="{'text-positive': strategyDebitCredit <= 0, 'text-negative': strategyDebitCredit > 0}">{{ formatCurrency(Math.abs(strategyDebitCredit)) }}</span></div><div v-for="(value, greek) in strategyGreeks" :key="greek" class="flex items-center space-x-1"><span class="text-foreground/70 capitalize">{{ greek }}</span><span class="font-semibold" :class="{'text-positive': value > 0, 'text-negative': value < 0}">{{ formatGreek(value) }}</span></div><button @click="showProfile" class="bg-accent hover:bg-accent/90 text-accent-foreground font-bold py-2 px-4 rounded-md ml-4!">View Risk Profile</button></div></div><div class="overflow-x-auto"><table class="min-w-full text-sm"><thead class="text-xs text-foreground/70 uppercase"><tr><th class="py-2 px-3 text-left font-medium">Side</th><th class="py-2 px-3 text-left font-medium">Qty</th><th class="py-2 px-3 text-left font-medium">Description</th><th class="py-2 px-3 text-right font-medium">Actions</th></tr></thead><tbody class="divide-y divide-border"><tr v-for="leg in strategyLegs" :key="leg.id"><td class="p-2 font-semibold" :class="leg.side === 'Buy' ? 'text-positive' : 'text-negative'">{{ leg.side }}</td><td class="p-2"><input type="number" v-model.number="leg.quantity" class="w-20 bg-background text-foreground rounded-md px-2 py-1 border border-border"/></td><td class="p-2">{{ leg.contract.localSymbol }}</td><td class="p-2 text-right"><button @click="removeLeg(leg.id)" class="text-negative hover:text-negative/80">Remove</button></td></tr></tbody></table></div><div class="mt-6 flex items-center space-x-4 border-t border-border pt-4"><input v-model="strategyName" type="text" placeholder="Enter name to save strategy" class="flex-grow bg-background text-foreground rounded-md px-4 py-2 border border-border"/><button @click="saveStrategy" class="bg-positive/80 hover:bg-positive/70 text-white font-bold py-2 px-4 rounded-md whitespace-nowrap">Save Strategy</button></div></div><div v-if="isLoading && chain.length === 0" class="text-center py-8 text-foreground/70">Loading Analytics & Chain Data...</div><div v-if="error" class="text-center py-8 text-negative">{{ error }}</div><OptionChainTable v-if="chain.length > 0" :chain="chain" :und-price="undPrice" @add-leg="handleAddLeg"/><div v-if="isProfileVisible" @click="isProfileVisible = false" class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50"><div @click.stop class="bg-secondary rounded-lg shadow-xl w-full max-w-6xl p-6"><div class="flex justify-between items-center mb-4"><h2 class="text-xl font-bold">Theoretical Risk Profile</h2><button @click="isProfileVisible = false" class="text-2xl leading-none text-foreground/70 hover:text-foreground">&times;</button></div><div v-if="isProfileLoading" class="text-center py-16 text-foreground/70">Calculating profile...</div><div v-else-if="profileError" class="text-center py-16 text-negative">{{ profileError }}</div><RiskProfileChart v-else-if="profileData" :chart-data="profileData" /></div></div></div>
</template>