export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui"] },
      colors: {
        aegis: {
          bg: "#0b0f19",
          card: "#1a2234",
          border: "#2d3a4f",
          text: "#f1f5f9",
          muted: "#94a3b8",
          green: "#22c55e",
          blue: "#3b82f6",
          purple: "#a855f7",
          orange: "#f59e0b",
          red: "#ef4444"
        }
      },
      borderRadius: { card: "14px", button: "8px" },
      boxShadow: { glow: "0 0 34px rgba(59, 130, 246, 0.22)" },
      animation: {
        mesh: "mesh 16s ease-in-out infinite",
        slideAway: "slideAway 320ms ease-in forwards"
      },
      keyframes: {
        mesh: {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%": { transform: "translate3d(2%, -2%, 0) scale(1.04)" }
        },
        slideAway: {
          "0%": { transform: "translateX(0)", opacity: "1" },
          "100%": { transform: "translateX(120%)", opacity: "0" }
        }
      }
    }
  },
  plugins: []
};
