// Tailwind contributes only its preflight reset; the design system itself lives as plain
// CSS in src/style.css (ported from the approved design demo). Keep this config token-free
// so there is a single source of design tokens.
module.exports = {
  content: ["./src/**/*.{html,js}"],
  theme: {
    extend: {},
  },
  plugins: [],
}
