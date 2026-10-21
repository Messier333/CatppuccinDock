import js from "@eslint/js";
import vue from "eslint-plugin-vue";
import globals from "globals";

export default [
  { ignores: ["dist/**", "node_modules/**"] },
  { ...js.configs.recommended, files: ["**/*.{js,mjs,vue}"] },
  ...vue.configs["flat/essential"],
  {
    files: ["src/**/*.{js,vue}"],
    languageOptions: { globals: globals.browser },
  },
  {
    files: ["tests/**/*.mjs", "vite.config.js", "eslint.config.js"],
    languageOptions: { globals: globals.node },
  },
  {
    files: ["public/sw.js"],
    languageOptions: { globals: globals.serviceworker },
  },
  {
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" }],
    },
  },
];
