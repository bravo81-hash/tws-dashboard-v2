/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class', // We are telling Tailwind to use a 'dark' class on the <html> element
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Here we define our new semantic color names.
      // The values are CSS variables that we will define in our CSS file.
      colors: {
        border: 'hsl(var(--border))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        positive: 'hsl(var(--positive))',
        negative: 'hsl(var(--negative))',
      },
    },
  },
  plugins: [],
}