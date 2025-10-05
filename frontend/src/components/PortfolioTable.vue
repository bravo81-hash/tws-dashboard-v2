<script setup>
import { ref, watch, computed } from 'vue';
// Import the new function
import { formatCurrency, formatNumber, formatPnlWithPercent } from '@/utils/formatters.js';

const props = defineProps({
  positions: Array,
  isLoading: Boolean,
  error: String,
});
const emit = defineEmits(['update:selectedPositions', 'combo-created']);

const selectedConIds = ref(new Set());
const filterText = ref('');
const newComboName = ref('');
const newComboGroup = ref('');

const filteredPositions = computed(() => {
  if (!filterText.value) {
    return props.positions;
  }
  const lowerCaseFilter = filterText.value.toLowerCase();
  return props.positions.filter(p =>
    p.description.toLowerCase().includes(lowerCaseFilter)
  );
});

async function createCombo() {
  if (!newComboName.value || selectedConIds.value.size === 0) {
    alert('Please enter a name and select at least one position.');
    return;
  }
  try {
    await fetch('http://127.0.0.1:8000/combos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newComboName.value,
        group: newComboGroup.value || 'Default',
        legConIds: Array.from(selectedConIds.value),
      }),
    });
    newComboName.value = '';
    newComboGroup.value = '';
    emit('combo-created');
  } catch (e) {
    console.error("Failed to create combo:", e);
  }
}

function toggleSelection(conId) {
  if (selectedConIds.value.has(conId)) {
    selectedConIds.value.delete(conId);
  } else {
    selectedConIds.value.add(conId);
  }
}

watch(selectedConIds, (newSelection) => {
  emit('update:selectedPositions', newSelection);
}, { deep: true });
</script>

<template>
  <div class="bg-secondary text-secondary-foreground rounded-lg shadow-lg p-6">
    <div class="flex justify-start items-center space-x-6 mb-4">
      <h2 class="text-2xl font-bold whitespace-nowrap">My Live Positions</h2>
      <input
        v-model="filterText"
        type="text"
        placeholder="Filter by name..."
        class="bg-background text-foreground rounded-md px-4 py-2 border border-border w-64"
      />
      <div class="flex items-center space-x-2 flex-grow">
        <input
          v-model="newComboName"
          type="text"
          placeholder="Enter new combo name"
          class="flex-grow bg-background text-foreground rounded-md px-4 py-2 border border-border"
        />
        <input
          v-model="newComboGroup"
          type="text"
          placeholder="Group (optional)"
          class="bg-background text-foreground rounded-md px-4 py-2 border border-border w-48"
        />
        <button @click="createCombo" class="bg-accent hover:bg-accent/90 text-accent-foreground font-bold py-2 px-4 rounded-md whitespace-nowrap">
          Create Combo ({{ selectedConIds.size }} legs)
        </button>
      </div>
    </div>
    
    <div v-if="isLoading">Loading...</div>
    <div v-else-if="error">Error: {{ error }}</div>
    <div v-else-if="filteredPositions.length === 0">No positions match your filter.</div>
    <div v-else class="overflow-x-auto">
      <table class="min-w-full divide-y divide-border">
        <thead class="">
          <tr>
            <th class="p-3 w-12"></th>
            <th class="p-3 text-left text-xs font-semibold text-foreground/70">Position</th>
            <th class="p-3 text-right text-xs font-semibold text-foreground/70">Qty</th>
            <th class="p-3 text-right text-xs font-semibold text-foreground/70">Avg Cost</th>
            <th class="p-3 text-right text-xs font-semibold text-foreground/70">Market Value</th>
            <th class="p-3 text-right text-xs font-semibold text-foreground/70">Daily P&L</th>
            <th class="p-3 text-right text-xs font-semibold text-foreground/70">Unrealized P&L</th>
            <th class="p-3 text-left text-xs font-semibold text-foreground/70">Status</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr v-for="p in filteredPositions" :key="p.conId" class="hover:bg-background/50">
            <td class="p-3">
              <input type="checkbox" class="h-4 w-4 rounded bg-background border-border text-accent focus:ring-accent" :checked="selectedConIds.has(p.conId)" @change="toggleSelection(p.conId)"/>
            </td>
            <td class="p-3 font-medium">{{ p.description }}</td>
            <td class="p-3 text-right">{{ formatNumber(p.position, 0) }}</td>
            <td class="p-3 text-right">{{ formatCurrency(p.avgCost) }}</td>
            <td class="p-3 text-right">{{ formatCurrency(p.marketValue) }}</td>
            <td class="p-3 text-right font-semibold" :class="p.pnl.daily >= 0 ? 'text-positive' : 'text-negative'">
              {{ formatPnlWithPercent(p.pnl.daily, p.costBasis) }}
            </td>
            <td class="p-3 text-right font-semibold" :class="p.pnl.unrealized >= 0 ? 'text-positive' : 'text-negative'">
              {{ formatPnlWithPercent(p.pnl.unrealized, p.costBasis) }}
            </td>
            <td class="p-3">{{ p.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>