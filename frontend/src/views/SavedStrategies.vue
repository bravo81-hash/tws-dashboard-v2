<script setup>
import { ref, onMounted, watch } from 'vue';
import { formatCurrency, formatGreek } from '@/utils/formatters.js';

const savedStrategies = ref([]);
const tickerFilter = ref('');
const isLoading = ref(false);
const error = ref(null);
const expandedId = ref(null);

// NEW: State to hold live tracked data and loading status for each row
const trackedData = ref({});
const trackingStatus = ref({});

async function fetchStrategies() {
  isLoading.value = true;
  error.value = null;
  let url = 'http://127.0.0.1:8000/strategies/';
  if (tickerFilter.value) {
    url += `?ticker=${tickerFilter.value.toUpperCase()}`;
  }

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error('Failed to fetch strategies.');
    savedStrategies.value = await response.json();
  } catch (e) {
    error.value = e.message;
    console.error(e);
  } finally {
    isLoading.value = false;
  }
}

async function deleteStrategy(strategyId) {
  if (!confirm('Are you sure you want to delete this saved strategy?')) return;

  try {
    const response = await fetch(`http://127.0.0.1:8000/strategies/${strategyId}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error('Failed to delete strategy.');
    fetchStrategies();
  } catch (e) {
    alert(e.message);
    console.error(e);
  }
}

// NEW: Function to fetch live data for a single strategy
async function trackStrategy(strategyId) {
  trackingStatus.value[strategyId] = true;
  trackedData.value[strategyId] = null; // Clear old data

  try {
    const response = await fetch(`http://127.0.0.1:8000/strategies/${strategyId}/track`, {
      method: 'POST',
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to track strategy.');
    }
    trackedData.value[strategyId] = await response.json();
  } catch (e) {
    alert(e.message);
    console.error(e);
  } finally {
    trackingStatus.value[strategyId] = false;
  }
}

function toggleDetails(strategyId) {
  expandedId.value = expandedId.value === strategyId ? null : strategyId;
}

onMounted(fetchStrategies);
watch(tickerFilter, fetchStrategies);

</script>

<template>
  <div class="bg-secondary text-secondary-foreground rounded-lg shadow-lg p-6 max-w-7xl mx-auto">
    <div class="flex justify-between items-center mb-4">
      <h2 class="text-2xl font-bold">Saved Strategies</h2>
      <div class="flex items-center space-x-4">
        <input v-model="tickerFilter" type="text" placeholder="Filter by ticker..." class="bg-background text-foreground rounded-md px-4 py-2 border border-border w-64"/>
      </div>
    </div>

    <div v-if="isLoading" class="text-center py-8 text-foreground/70">Loading strategies...</div>
    <div v-if="error" class="text-center py-8 text-negative">{{ error }}</div>
    
    <div v-if="!isLoading && savedStrategies.length === 0" class="text-foreground/60 text-center py-8">No saved strategies found.</div>

    <div v-else class="overflow-x-auto">
      <table class="min-w-full">
        <thead class="border-b border-border text-xs font-semibold text-foreground/70">
          <tr>
            <th class="p-3 text-left">Name</th>
            <th class="p-3 text-left">Ticker</th>
            <th class="p-3 text-center">Legs</th>
            <th class="p-3 text-right">Cost Basis</th>
            <th class="p-3 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="strategy in savedStrategies" :key="strategy.id">
            <tr @click="toggleDetails(strategy.id)" class="border-b border-border hover:bg-background/50 cursor-pointer">
              <td class="p-3 font-semibold">{{ strategy.name }}</td>
              <td class="p-3">{{ strategy.ticker }}</td>
              <td class="p-3 text-center">{{ strategy.legs.length }}</td>
              <td class="p-3 text-right font-semibold" :class="strategy.cost_basis > 0 ? 'text-negative' : 'text-positive'">{{ formatCurrency(strategy.cost_basis) }}</td>
              <td class="p-3 text-right space-x-4">
                <button @click.stop="trackStrategy(strategy.id)" class="text-sm text-accent hover:text-accent/80" :disabled="trackingStatus[strategy.id]">
                  {{ trackingStatus[strategy.id] ? 'Tracking...' : 'Track' }}
                </button>
                <button @click.stop="deleteStrategy(strategy.id)" class="text-sm text-negative hover:text-negative/80">Delete</button>
              </td>
            </tr>
            <tr v-if="expandedId === strategy.id">
              <td colspan="5" class="p-0">
                <div class="bg-background/50 px-6 py-4 grid grid-cols-3 gap-4">
                  <div>
                    <h4 class="text-sm font-semibold mb-2">Legs:</h4>
                    <ul class="list-disc pl-5 space-y-1 text-sm">
                      <li v-for="(leg, index) in strategy.legs" :key="index">
                        <span class="font-semibold" :class="leg.side === 'Buy' ? 'text-positive' : 'text-negative'">{{ leg.side }} {{ leg.quantity }}</span>
                        <span> - {{ leg.contract.localSymbol }}</span>
                      </li>
                    </ul>
                  </div>
                  <div class="col-span-2">
                    <div v-if="trackingStatus[strategy.id]">Tracking live data...</div>
                    <div v-if="trackedData[strategy.id]" class="space-y-2">
                      <h4 class="text-sm font-semibold">Live Market Data</h4>
                      <div class="grid grid-cols-3 gap-x-4 gap-y-1 text-sm font-mono p-3 bg-background rounded-md">
                        <span class="text-foreground/70">Bid:</span><span class="col-span-2 font-semibold text-right">{{ formatCurrency(trackedData[strategy.id].bid) }}</span>
                        <span class="text-foreground/70">Mid:</span><span class="col-span-2 font-semibold text-right">{{ formatCurrency(trackedData[strategy.id].mid) }}</span>
                        <span class="text-foreground/70">Ask:</span><span class="col-span-2 font-semibold text-right">{{ formatCurrency(trackedData[strategy.id].ask) }}</span>
                      </div>
                      <div class="grid grid-cols-4 gap-x-4 gap-y-1 text-sm font-mono p-3 bg-background rounded-md">
                        <span class="text-foreground/70">Delta:</span><span class="font-semibold text-right">{{ formatGreek(trackedData[strategy.id].delta) }}</span>
                        <span class="text-foreground/70">Gamma:</span><span class="font-semibold text-right">{{ formatGreek(trackedData[strategy.id].gamma) }}</span>
                        <span class="text-foreground/70">Vega:</span><span class="font-semibold text-right">{{ formatGreek(trackedData[strategy.id].vega) }}</span>
                        <span class="text-foreground/70">Theta:</span><span class="font-semibold text-right">{{ formatGreek(trackedData[strategy.id].theta) }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>