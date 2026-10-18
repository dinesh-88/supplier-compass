import { defineConfig } from "@playwright/test";

const PORT = 8010;
const LLM_PORT = 8011;
const python = process.env.PYTHON ?? "../.venv/bin/python";

// Runs the real backend (serving the built frontend) against a test-only fake LLM and a throwaway data dir.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1280, height: 800 } },
  webServer: [
    {
      command: `${python} e2e/fake_llm.py ${LLM_PORT}`,
      url: `http://127.0.0.1:${LLM_PORT}/v1/models`,
      reuseExistingServer: false,
    },
    {
      command:
        `rm -rf ../var-e2e && cd ../backend && DATA_DIR=../var-e2e APP_USERS=jury:jury-e2e SECRET_KEY=e2e ` +
        `LLM_BASE_URL=http://127.0.0.1:${LLM_PORT}/v1/ LLM_API_KEY=e2e LLM_MODEL=e2e-fake TAVILY_API_KEY= ` +
        `STATIC_DIR=../frontend/dist ${python} -m uvicorn app.main:app --port ${PORT}`,
      url: `http://127.0.0.1:${PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
