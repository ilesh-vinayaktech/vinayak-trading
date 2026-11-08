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
      },
    },
  },
  plugins: [],
};
export default config;
