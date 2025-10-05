<script setup>
import { ref, onMounted, computed } from 'vue';
import { formatCurrency, formatGreek, formatPnlWithPercent, formatDate } from '@/utils/formatters.js';
import RiskProfileChart from './RiskProfileChart.vue';
import RiskSurface3D from './RiskSurface3D.vue'; // <-- Import the new component

// --- Props ---
const props = defineProps({
  positions: Array,
});

// --- State Refs ---
const combos = ref([]);
const expandedComboId = ref(null);
const nameFilter = ref('');

// --- State for 2D Profile Modal ---
const is2dModalVisible = ref(false);
const selectedComboForProfile = ref(null);
const chartData2d = ref(null);
const is2dChartLoading = ref(false);

// --- NEW: State for 3D Surface Modal ---
const is3dModalVisible = ref(false);
const surfaceData3d = ref(null);
const is3dSurfaceLoading = ref(false);
const chartError = ref(null);

// --- Computed Properties ---
const positionMap = computed(() => {
  return new Map(props.positions.map(p => [p.conId, p]));
});

// --- Methods ---
async function fetchCombos() { /* ... unchanged ... */ try { const response = await fetch('http://127.0.0.1:8000/combos'); combos.value = await response.json(); } catch (e) { console.error("Failed to fetch combos:", e); } }
async function deleteCombo(comboId) { /* ... unchanged ... */ if (!confirm('Are you sure you want to delete this combo?')) return; try { await fetch(`http://127.0.0.1:8000/combos/${comboId}`, { method: 'DELETE' }); await fetchCombos(); } catch (e) { console.error("Failed to delete combo:", e); } }
function toggleDetails(comboId) { /* ... unchanged ... */ if (expandedComboId.value === comboId) { expandedComboId.value = null; } else { expandedComboId.value = comboId; } }

async function showRiskProfile(combo) {
  selectedComboForProfile.value = combo;
  is2dChartLoading.value = true;
  chartData2d.value = null;
  chartError.value = null;
  is2dModalVisible.value = true;

  try {
    const response = await fetch('http://127.0.0.1:8000/combos/risk-profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ legConIds: combo.legConIds }),
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to fetch risk profile');
    }
    chartData2d.value = await response.json();
  } catch (error) {
    chartError.value = error.message;
    console.error("Error fetching 2D risk profile:", error);
  } finally {
    is2dChartLoading.value = false;
  }
}

// NEW: Method to fetch 3D surface data and show modal
async function show3dSurface(combo) {
  selectedComboForProfile.value = combo;
  is3dSurfaceLoading.value = true;
  surfaceData3d.value = null;
  chartError.value = null;
  is3dModalVisible.value = true;

  try {
    const response = await fetch('http://127.0.0.1:8000/combos/3d-surface', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ legConIds: combo.legConIds }),
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to fetch 3D surface data.');
    }
    surfaceData3d.value = await response.json();
  } catch (error) {
    chartError.value = error.message;
    console.error("Error fetching 3D surface:", error);
  } finally {
    is3dSurfaceLoading.value = false;
  }
}

defineExpose({ fetchCombos });
onMounted(fetchCombos);
</script>

<template>
  <div class="bg-secondary text-secondary-foreground rounded-lg shadow-lg p-6">
    <div class="flex justify-between items-center mb-4"><h2 class="text-2xl font-bold">Custom Combos</h2><div class="flex items-center space-x-4"><input v-model="nameFilter" type="text" placeholder="Filter by name..." class="bg-background text-foreground rounded-md px-4 py-2 border border-border w-64"/></div></div>
    
    <div class="overflow-x-auto">
      <div v-if="combos.length === 0" class="text-foreground/60 text-center py-8">No combos have been created.</div>
      <table v-else class="min-w-full">
        <thead class="border-b border-border text-xs font-semibold text-foreground/70"><tr><th rowspan="2" class="p-3 text-left align-bottom">Combo Name</th><th colspan="3" class="p-2 text-center border-x border-border">Financials</th><th colspan="4" class="p-2 text-center border-x border-border">Greeks</th><th rowspan="2" class="p-3 text-left align-bottom">DTE</th><th rowspan="2" class="p-3 text-right align-bottom">Actions</th></tr><tr><th class="py-2 px-3 text-right font-semibold border-l border-border">Cost Basis</th><th class="py-2 px-3 text-right font-semibold">Unrealized P&L</th><th class="py-2 px-3 text-right font-semibold border-r border-border">Daily P&L</th><th class="py-2 px-3 text-right font-semibold">Delta</th><th class="py-2 px-3 text-right font-semibold border-x border-border">Gamma</th><th class="py-2 px-3 text-right font-semibold">Theta</th><th class="py-2 px-3 text-right font-semibold border-r border-border">Vega</th></tr></thead>
        <tbody>
          <template v-for="combo in combos" :key="combo.id">
            <tr @click="toggleDetails(combo.id)" class="border-b border-border hover:bg-background/50 cursor-pointer">
              <td class="p-3 font-semibold">{{ combo.name }}</td>
              <td class="p-3 text-right border-l border-border">{{ formatCurrency(combo.costBasis) }}</td>
              <td class="p-3 text-right font-semibold" :class="combo.unrealizedPnl >= 0 ? 'text-positive' : 'text-negative'">{{ formatPnlWithPercent(combo.unrealizedPnl, combo.costBasis) }}</td>
              <td class="p-3 text-right font-semibold border-r border-border" :class="combo.dailyPnl >= 0 ? 'text-positive' : 'text-negative'">{{ formatPnlWithPercent(combo.dailyPnl, combo.costBasis) }}</td>
              <td class="p-3 text-right">{{ formatGreek(combo.delta) }}</td>
              <td class="p-3 text-right border-x border-border">{{ formatGreek(combo.gamma) }}</td>
              <td class="p-3 text-right">{{ formatGreek(combo.theta) }}</td>
              <td class="p-3 text-right border-r border-border">{{ formatGreek(combo.vega) }}</td>
              <td class="p-3 text-left text-sm">{{ combo.dte }}</td>
              <td class="p-3 text-right">
                <button @click.stop="show3dSurface(combo)" class="text-sm text-accent hover:text-accent/80">3D</button>
                <button @click.stop="showRiskProfile(combo)" class="ml-4 text-sm text-accent hover:text-accent/80">Profile</button>
                <button @click.stop="deleteCombo(combo.id)" class="ml-4 text-sm text-negative hover:text-negative/80">Delete</button>
              </td>
            </tr>
            <tr v-if="expandedComboId === combo.id"><td colspan="10" class="p-0"><div class="bg-background/50 px-6 py-3"><table class="w-full text-sm"><thead><tr class="border-b border-border/50"><th class="pb-2 text-left font-normal text-foreground/70">Leg</th><th class="pb-2 text-right font-normal text-foreground/70">Qty</th><th class="pb-2 text-right font-normal text-foreground/70">Market Value</th><th class="pb-2 text-right font-normal text-foreground/70">Unr. P&L</th></tr></thead><tbody><tr v-for="conId in combo.legConIds" :key="conId"><td class="py-1">{{ positionMap.get(conId)?.description || `ID: ${conId}` }}</td><td class="py-1 text-right">{{ positionMap.get(conId)?.position }}</td><td class="py-1 text-right">{{ formatCurrency(positionMap.get(conId)?.marketValue) }}</td><td class="py-1 text-right" :class="positionMap.get(conId)?.pnl.unrealized >= 0 ? 'text-positive' : 'text-negative'">{{ formatCurrency(positionMap.get(conId)?.pnl.unrealized) }}</td></tr></tbody></table></div></td></tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="is2dModalVisible" @click="is2dModalVisible = false" class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50">
    <div @click.stop class="bg-secondary rounded-lg shadow-xl w-full max-w-6xl p-6">
      <div class="flex justify-between items-center mb-4"><h2 class="text-xl font-bold">Risk Profile: {{ selectedComboForProfile.name }}</h2><button @click="is2dModalVisible = false" class="text-2xl leading-none text-foreground/70 hover:text-foreground">&times;</button></div>
      <div v-if="is2dChartLoading" class="text-center py-16 text-foreground/70">Loading chart data...</div>
      <div v-else-if="chartError" class="text-center py-16 text-negative">{{ chartError }}</div>
      <RiskProfileChart v-else-if="chartData2d" :chart-data="chartData2d" />
    </div>
  </div>

  <div v-if="is3dModalVisible" @click="is3dModalVisible = false" class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50">
    <div @click.stop class="bg-secondary rounded-lg shadow-xl w-full max-w-6xl p-6">
      <div class="flex justify-between items-center mb-4"><h2 class="text-xl font-bold">3D P&L Surface: {{ selectedComboForProfile.name }}</h2><button @click="is3dModalVisible = false" class="text-2xl leading-none text-foreground/70 hover:text-foreground">&times;</button></div>
      <div v-if="is3dSurfaceLoading" class="text-center py-16 text-foreground/70">Calculating 3D surface data...</div>
      <div v-else-if="chartError" class="text-center py-16 text-negative">{{ chartError }}</div>
      <RiskSurface3D v-else-if="surfaceData3d" :surface-data="surfaceData3d" />
    </div>
  </div>

</template>