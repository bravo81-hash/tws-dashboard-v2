<script setup>
// ... (imports are the same)
import { computed } from 'vue';
import { formatCurrency, formatNumber, formatGreek } from '@/utils/formatters.js';

// ... (props are the same)
const props = defineProps({ chain: { type: Array, required: true }, undPrice: { type: Number, required: true } });

const emit = defineEmits(['add-leg']);

// ... (atTheMoneyStrike is the same)
const atTheMoneyStrike = computed(() => {
  if (!props.chain || props.chain.length === 0) return 0;
  const closestRow = props.chain.reduce((prev, curr) => {
    return (Math.abs(curr.strike - props.undPrice) < Math.abs(prev.strike - props.undPrice) ? curr : prev);
  });
  return closestRow.strike;
});


function onAddLegClick(optionData, side) {
  if (!optionData || !optionData.contract) return;
  // --- THIS IS THE CHANGE ---
  // We now emit the entire object, including contract details and market data
  emit('add-leg', {
    optionData: optionData, // Contains contract and data objects
    side: side,
  });
}
</script>

<template>
  <div class="overflow-x-auto bg-background rounded-md border border-border">
    <table class="min-w-full text-sm">
      <thead class="text-xs text-foreground/70 uppercase border-b border-border">
        <tr>
          <th colspan="7" class="py-3 px-4 text-center font-semibold">Calls</th>
          <th class="py-3 px-4 text-center font-semibold border-x border-border">Strike</th>
          <th colspan="7" class="py-3 px-4 text-center font-semibold">Puts</th>
        </tr>
        <tr>
          <th class="py-2 px-3 text-right font-medium">IV</th>
          <th class="py-2 px-3 text-right font-medium">Delta</th>
          <th class="py-2 px-3 text-right font-medium">Bid</th>
          <th class="py-2 px-3 text-right font-medium">Ask</th>
          <th class="py-2 px-3 text-center font-medium">B/S</th>
          <th class="py-2 px-3 text-left font-medium">Symbol</th>
          <th class="py-2 px-3 text-right font-medium border-r border-border">Open Int</th>
          <th class="py-2 px-3 text-center border-x border-border"></th>
          <th class="py-2 px-3 text-right font-medium border-l border-border">Open Int</th>
          <th class="py-2 px-3 text-left font-medium">Symbol</th>
          <th class="py-2 px-3 text-center font-medium">B/S</th>
          <th class="py-2 px-3 text-right font-medium">Bid</th>
          <th class="py-2 px-3 text-right font-medium">Ask</th>
          <th class="py-2 px-3 text-right font-medium">Delta</th>
          <th class="py-2 px-3 text-right font-medium">IV</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-border">
        <tr v-for="row in chain" :key="row.strike" class="hover:bg-secondary" :class="{ 'bg-accent/10': row.strike === atTheMoneyStrike }">
          <td class="p-2 text-right text-foreground/80">{{ formatNumber(row.call?.data?.iv * 100, 1) }}%</td>
          <td class="p-2 text-right text-foreground/80">{{ formatGreek(row.call?.data?.delta) }}</td>
          <td class="p-2 text-right">{{ formatCurrency(row.call?.data?.bid) }}</td>
          <td class="p-2 text-right">{{ formatCurrency(row.call?.data?.ask) }}</td>
          <td class="p-2 text-center whitespace-nowrap"><button @click="onAddLegClick(row.call, 'Buy')" class="w-5 h-5 leading-5 rounded text-xs font-bold bg-blue-500/20 text-blue-300 hover:bg-blue-500/40">B</button><button @click="onAddLegClick(row.call, 'Sell')" class="w-5 h-5 leading-5 rounded text-xs font-bold bg-red-500/20 text-red-300 hover:bg-red-500/40 ml-1">S</button></td>
          <td class="p-2 text-left font-mono text-xs">{{ row.call?.contract?.localSymbol }}</td>
          <td class="p-2 text-right text-foreground/80 border-r border-border">N/A</td>
          <td class="p-2 text-center font-bold border-x border-border">{{ formatNumber(row.strike) }}</td>
          <td class="p-2 text-right text-foreground/80 border-l border-border">N/A</td>
          <td class="p-2 text-left font-mono text-xs">{{ row.put?.contract?.localSymbol }}</td>
          <td class="p-2 text-center whitespace-nowrap"><button @click="onAddLegClick(row.put, 'Buy')" class="w-5 h-5 leading-5 rounded text-xs font-bold bg-blue-500/20 text-blue-300 hover:bg-blue-500/40">B</button><button @click="onAddLegClick(row.put, 'Sell')" class="w-5 h-5 leading-5 rounded text-xs font-bold bg-red-500/20 text-red-300 hover:bg-red-500/40 ml-1">S</button></td>
          <td class="p-2 text-right">{{ formatCurrency(row.put?.data?.bid) }}</td>
          <td class="p-2 text-right">{{ formatCurrency(row.put?.data?.ask) }}</td>
          <td class="p-2 text-right text-foreground/80">{{ formatGreek(row.put?.data?.delta) }}</td>
          <td class="p-2 text-right text-foreground/80">{{ formatNumber(row.put?.data?.iv * 100, 1) }}%</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>