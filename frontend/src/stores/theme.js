// frontend/src/stores/theme.js
import { ref, watchEffect } from 'vue';

// Get the saved theme from localStorage, or default to 'dark'
export const theme = ref(localStorage.getItem('theme') || 'dark');

export function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light';
}

// This effect runs whenever the 'theme' ref changes
watchEffect(() => {
  // Update localStorage with the new theme
  localStorage.setItem('theme', theme.value);
  // Add or remove the 'dark' class from the main <html> element
  if (theme.value === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
});