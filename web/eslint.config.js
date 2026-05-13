// ESLint v9 flat-config shim that bridges to the existing legacy
// ``.eslintrc.js``. Without this, `eslint --fix` invoked by lint-staged
// in the pre-commit hook fails to find a config file (`pnpm lint` works
// because Next.js routes through its own ESLint integration which still
// honours .eslintrc-style configs).
//
// Migrating the full rule set to flat-config is a separate cleanup; this
// shim keeps the existing rules wired without forcing that diff today.

const { FlatCompat } = require("@eslint/eslintrc");

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const legacy = require("./.eslintrc.js");

module.exports = [
  {
    // `next lint` excluded the root config files implicitly; the ESLint
    // CLI does not, so list them here. The TS parser-with-project would
    // otherwise complain that these files aren't in tsconfig.json.
    ignores: [
      ...(legacy.ignorePatterns || []),
      ".eslintrc.js",
      "eslint.config.js",
      "next.config.js",
      "postcss.config.js",
      "tailwind.config.ts",
    ],
  },
  ...compat.config(legacy),
];
