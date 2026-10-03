import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended, reactHooks.configs.flat.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
  },
  {
    files: ["tests/**/*.mjs", "*.config.{js,ts}"],
    extends: [js.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.node },
  },
  {
    files: ["vite.config.ts"],
    extends: [...tseslint.configs.recommended],
  },
);
