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
        AbortController: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        MutationObserver: "readonly",
        requestAnimationFrame: "readonly",
        FileReader: "readonly",
        URL: "readonly",
        Date: "readonly",
        JSON: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "no-redeclare": "error",
    },
  },
  {
    // Deferred classic-script modules that consume app.js's top-level
    // `const state` as a bare global (script load order guarantees it is
    // bound before these run). app.js itself is excluded so its own
    // declaration doesn't trip no-redeclare.
    files: [
      "src/job_agent/ui/static/drawer.js",
      "src/job_agent/ui/static/kanban.js",
      "src/job_agent/ui/static/overview.js",
      "src/job_agent/ui/static/palette.js",
      "src/job_agent/ui/static/features.js",
      "src/job_agent/ui/static/profile_editor.js",
      "src/job_agent/ui/static/pipeline.js",
      "src/job_agent/ui/static/studio.js",
      "src/job_agent/ui/static/studio_tools.js",
      "src/job_agent/ui/static/portfolio.js",
      "src/job_agent/ui/static/coach.js",
      "src/job_agent/ui/static/autopilot.js",
      "src/job_agent/ui/static/insights.js",
    ],
    languageOptions: {
      globals: {
        state: "readonly",
        // top-level const in app.js (script scope, not on window) — modules
        // read it as a bare identifier at call time, same as `state`
        autoApplyState: "readonly",
      },
    },
  },
];
