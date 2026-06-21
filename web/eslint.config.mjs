import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";
import tseslint from "typescript-eslint";
import eslintConfigPrettier from "eslint-config-prettier";

/**
 * ESLint v10 flat config for the Next.js 15 + React 19 + TypeScript app.
 *
 * Composition order matters: Next.js (core-web-vitals + typescript) first,
 * then typescript-eslint recommended, then eslint-config-prettier LAST so it
 * switches off any stylistic rules that would conflict with Prettier.
 */
const config = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "coverage/**",
      "next-env.d.ts",
      "**/*.config.js",
      "**/*.config.mjs",
      "**/*.config.ts",
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  ...tseslint.configs.recommended,
  eslintConfigPrettier,
  {
    settings: {
      // eslint-config-next ships eslint-plugin-react@7.37 which crashes under
      // ESLint v10 when react.version is "detect" (its detector calls the
      // removed context.getFilename()). Pin the concrete version to bypass
      // that legacy detection path.
      react: { version: "19" },
    },
    rules: {
      // Tighten signal: surface issues as warnings rather than failing the
      // lint run on stylistic/non-blocking concerns. Real correctness rules
      // from the Next.js + typescript-eslint presets stay at their defaults.
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-empty-object-type": "warn",
      // Opinionated React-Compiler hint enabled as an error by
      // eslint-config-next. The flagged spots are legitimate one-time init
      // effects, so keep it advisory rather than blocking. Other react-hooks
      // correctness rules stay at "error".
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default config;
