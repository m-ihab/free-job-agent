export default [
  {
    files: ["src/job_agent/ui/static/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        Chart: "readonly",
        EventSource: "readonly",
        window: "readonly",
        document: "readonly",
        fetch: "readonly",
        getComputedStyle: "readonly",
        HTMLElement: "readonly",
        localStorage: "readonly",
        navigator: "readonly",
        console: "readonly",
        btoa: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    },
  },
];
