import { defineConfig } from "@playwright/test";

const PORT = 8010;
const python = process.env.PYTHON ?? "../.venv/bin/python";

// Runs the real backend (serving the built frontend) with mock LLM/search and a throwaway data dir.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1280, height: 800 } },
  webServer: {
    command:
      `rm -rf ../var-e2e && cd ../backend && DATA_DIR=../var-e2e APP_USERS=jury:jury-e2e MOCK_LLM=1 MOCK_SEARCH=1 ` +
      `SECRET_KEY=e2e STATIC_DIR=../frontend/dist ${python} -m uvicorn app.main:app --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/healthz`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
