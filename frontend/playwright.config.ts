import path from "node:path";
export default {
  testDir: "tests/e2e",
  workers: 1,
  timeout: 90000,
  outputDir: process.env.VOICE_BROWSER_OUTPUT || "test-results",
  use: {
    baseURL: process.env.VOICE_BASE_URL || "http://127.0.0.1:8096",
    viewport: { width: 1360, height: 1080 },
    trace: "off",
    video: "off",
    launchOptions: {
      executablePath: process.env.CHROME_PATH,
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--use-file-for-fake-audio-capture=" +
          path.resolve("../fixtures/greeting.wav") +
          "%noloop",
      ],
    },
  },
};
