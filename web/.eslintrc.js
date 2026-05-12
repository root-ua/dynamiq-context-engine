/** @type {import("eslint").Linter.Config} */
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: {
    project: "./tsconfig.json",
    tsconfigRootDir: __dirname,
    ecmaVersion: "latest",
    sourceType: "module",
  },
  plugins: ["@typescript-eslint"],
  extends: [
    "next/core-web-vitals",
    "plugin:@typescript-eslint/recommended-type-checked",
    "plugin:@typescript-eslint/stylistic-type-checked",
    "prettier",
  ],
  rules: {
    "@typescript-eslint/consistent-type-imports": [
      "error",
      { prefer: "type-imports", fixStyle: "inline-type-imports" },
    ],
    "@typescript-eslint/no-floating-promises": "error",
    "@typescript-eslint/no-misused-promises": [
      "error",
      { checksVoidReturn: { attributes: false } },
    ],
    "@typescript-eslint/await-thenable": "error",
    "@typescript-eslint/no-unused-vars": [
      "error",
      {
        argsIgnorePattern: "^_",
        varsIgnorePattern: "^_",
        caughtErrorsIgnorePattern: "^_",
      },
    ],
    "@typescript-eslint/no-explicit-any": "error",
    // The "unsafe-*" family is disabled because Next.js / BlockNote / rjsf
    // widely use `unknown`-typed externals; flipping these on produces hundreds
    // of noise findings with no real bug surface. Revisit if we migrate off
    // those dependencies.
    "@typescript-eslint/no-unsafe-assignment": "off",
    "@typescript-eslint/no-unsafe-member-access": "off",
    "@typescript-eslint/no-unsafe-call": "off",
    "@typescript-eslint/no-unsafe-return": "off",
    "@typescript-eslint/no-unsafe-argument": "off",
    "@typescript-eslint/no-redundant-type-constituents": "off",
    "@typescript-eslint/restrict-template-expressions": "off",
    "@typescript-eslint/unbound-method": "off",
    "@typescript-eslint/require-await": "warn",
    // Stylistic preferences; the project mixes both styles and we don't want
    // to churn the diff for mechanical taste issues. Keep the bug-catching
    // stylistic rules (prefer-nullish-coalescing, prefer-optional-chain,
    // no-unnecessary-type-assertion) enabled.
    "@typescript-eslint/array-type": "off",
    "@typescript-eslint/consistent-type-definitions": "off",
    "@typescript-eslint/dot-notation": "off",
    "@typescript-eslint/no-base-to-string": "warn",
    "@typescript-eslint/no-unnecessary-type-assertion": "warn",
    // `||` vs `??` semantics differ for "" / 0 / false. Many existing
    // `name || "Untitled"` style fallbacks intentionally rely on `||`. Keep
    // the rule off; reviewers can still spot-fix where null-ish intent is
    // unambiguous.
    "@typescript-eslint/prefer-nullish-coalescing": "off",
    "react/no-unescaped-entities": ["error", { forbid: [">", "}"] }],
  },
  ignorePatterns: [
    ".next/",
    "node_modules/",
    "e2e/",
    "**/*.d.ts",
    "next-env.d.ts",
    "vitest.config.*",
    "vitest.setup.*",
  ],
  overrides: [
    {
      // Tests can use slightly looser rules: empty mock methods, fake hrefs,
      // inline type assertions used to satisfy strict TS in scaffolded data.
      files: ["**/*.{test,spec}.{ts,tsx}", "vitest.setup.ts"],
      rules: {
        "@typescript-eslint/no-empty-function": "off",
        "@next/next/no-html-link-for-pages": "off",
        "@typescript-eslint/require-await": "off",
        "@typescript-eslint/no-unnecessary-type-assertion": "off",
      },
    },
  ],
};
