/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontSize: {
        xs: ["0.8125rem", { lineHeight: "1.125rem" }],
        sm: ["0.9375rem", { lineHeight: "1.375rem" }],
      },
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "slide-in-from-top": {
          "0%": { transform: "translateY(-8px)" },
          "100%": { transform: "translateY(0)" },
        },
        "dash-scroll": {
          "0%": { transform: "translateX(-50%)" },
          "100%": { transform: "translateX(0%)" },
        },
        "dash-scroll-v": {
          "0%": { transform: "translateY(-50%)" },
          "100%": { transform: "translateY(0%)" },
        },
        "shine": {
          "0%": { transform: "translateX(-150%) skewX(-15deg)" },
          "100%": { transform: "translateX(150%) skewX(-15deg)" },
        },
      },
      animation: {
        "in": "fade-in 0.2s ease-out, slide-in-from-top 0.2s ease-out",
        "dash-scroll": "dash-scroll 3s linear infinite",
        "dash-scroll-v": "dash-scroll-v 3s linear infinite",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
}
