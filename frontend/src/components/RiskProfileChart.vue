<script setup>
import { Line } from 'vue-chartjs';
import { Chart as ChartJS, Title, Tooltip, Legend, LineElement, PointElement, CategoryScale, LinearScale } from 'chart.js';
import { computed } from 'vue';

ChartJS.register(Title, Tooltip, Legend, LineElement, PointElement, CategoryScale, LinearScale);

const props = defineProps({
  chartData: Object,
});

const data = computed(() => {
    const curveLabels = Object.keys(props.chartData.curves);
    const palette = ['#22c55e', '#60a5fa', '#a78bfa', '#f472b6', '#ef4444']; // Green, Blue, Purple, Pink, Red

    return {
        labels: props.chartData.price_range.map(p => p.toFixed(2)),
        datasets: curveLabels.map((label, index) => ({
            label: label,
            borderColor: palette[index % palette.length],
            borderWidth: label === 'T+0' || label === 'Expiration' ? 2.5 : 1.5,
            pointRadius: 0,
            data: props.chartData.curves[label],
        }))
    }
});

const options = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  scales: {
    x: {
      title: { display: true, text: 'Underlying Price' },
      grid: { display: false }, // <-- Grid disabled
    },
    y: {
      title: { display: true, text: 'Profit / Loss ($)' },
      grid: { display: false }, // <-- Grid disabled
      ticks: { callback: (value) => `$${value.toLocaleString()}` },
    },
  },
};
</script>

<template>
  <div class="relative h-[60vh]">
    <Line :data="data" :options="options" />
  </div>
</template>