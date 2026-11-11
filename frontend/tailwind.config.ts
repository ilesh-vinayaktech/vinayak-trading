import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0f172a", soft: "#475569", faint: "#94a3b8" },
        panel: "#ffffff",
        canvas: "#f1f5f9",
        line: "#e2e8f0",
        brand: { DEFAULT: "#2563eb", dark: "#1d4ed8", soft: "#eff6ff" },
      },
      boxShadow: { card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 3px rgba(15, 23, 42, 0.06)" },
    },
  },
  plugins: [],
};
export default config;
