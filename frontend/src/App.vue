<script setup>
import { ref, onMounted } from 'vue';
import PortfolioTable from '@/components/PortfolioTable.vue';
import ComboManager from '@/components/ComboManager.vue';
import ThemeToggle from '@/components/ThemeToggle.vue';
import StrategyBuilder from '@/views/StrategyBuilder.vue';
import SavedStrategies from '@/views/SavedStrategies.vue'; // <-- 1. IMPORT THE NEW VIEW

const activeTab = ref('portfolio');
const comboManagerRef = ref(null);

const portfolio = ref([]);
const isLoading = ref(true);
const error = ref(null);
const selectedPositions = ref(new Set());

function handleComboCreated() {
  if (comboManagerRef.value) {
    comboManagerRef.value.fetchCombos();
    selectedPositions.value = new Set();
  }
}

async function fetchPortfolio() {
  try {
    const response = await fetch('http://127.0.0.1:8000/portfolio');
    if (!response.ok) throw new Error('Network response was not ok');
    portfolio.value = await response.json();
  } catch (e) {
    error.value = e.message;
    console.error("Failed to fetch portfolio:", e);
  } finally {
    isLoading.value = false;
  }
}

onMounted(fetchPortfolio);
</script>

<template>
  <main class="bg-background text-foreground min-h-screen p-4 md:p-8">
    <header class="max-w-7xl mx-auto mb-6 flex justify-between items-center">
      <div>
        <h1 class="text-3xl font-bold">TWS Interactive Dashboard</h1>
        <p class="text-secondary-foreground/80">Real-time risk, combos & PnL monitor</p>
      </div>
      <ThemeToggle />
    </header>

    <div class="mb-4 border-b border-border">
      <nav class="-mb-px flex space-x-6" aria-label="Tabs">
        <button
          @click="activeTab = 'portfolio'"
          :class="[
            'whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm',
            activeTab === 'portfolio'
              ? 'border-accent text-accent'
              : 'border-transparent text-secondary-foreground/60 hover:text-foreground hover:border-border'
          ]"
        >
          Portfolio
        </button>
        <button
          @click="activeTab = 'combos'"
          :class="[
            'whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm',
            activeTab === 'combos'
              ? 'border-accent text-accent'
              : 'border-transparent text-secondary-foreground/60 hover:text-foreground hover:border-border'
          ]"
        >
          Custom Combos
        </button>
        <button
          @click="activeTab = 'builder'"
          :class="[
            'whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm',
            activeTab === 'builder'
              ? 'border-accent text-accent'
              : 'border-transparent text-secondary-foreground/60 hover:text-foreground hover:border-border'
          ]"
        >
          Strategy Builder
        </button>
        
        <button
          @click="activeTab = 'saved'"
          :class="[
            'whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm',
            activeTab === 'saved'
              ? 'border-accent text-accent'
              : 'border-transparent text-secondary-foreground/60 hover:text-foreground hover:border-border'
          ]"
        >
          Saved Strategies
        </button>

      </nav>
    </div>

    <div>
      <div v-show="activeTab === 'portfolio'">
        <PortfolioTable
          :positions="portfolio"
          :is-loading="isLoading"
          :error="error"
          v-model:selectedPositions="selectedPositions"
          @combo-created="handleComboCreated"
        />
      </div>
      <div v-show="activeTab === 'combos'">
        <ComboManager ref="comboManagerRef" :positions="portfolio" />
      </div>
      <div v-show="activeTab === 'builder'">
        <StrategyBuilder />
      </div>

      <div v-show="activeTab === 'saved'">
        <SavedStrategies />
      </div>

    </div>
  </main>
</template>