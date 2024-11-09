import { test, expect, Page } from "@playwright/test";
import fs from "node:fs";
const config = process.env.VOICE_E2E_CONFIG
  ? JSON.parse(fs.readFileSync(process.env.VOICE_E2E_CONFIG, "utf8"))
  : {};
test.skip(
  !config.VOICE_WORKSPACE_KEY,
  "Supply private local credentials through VOICE_E2E_CONFIG."
);
async function create(page: Page) {
  await page.goto("/");
  await expect(page.getByText("Local services ready")).toBeVisible({
    timeout: 15000,
  });
  await page
    .getByLabel("Workspace key", { exact: true })
    .fill(config.VOICE_WORKSPACE_KEY);
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/api/sessions") && r.request().method() === "POST"
  );
  await page.getByRole("button", { name: "Create a conversation" }).click();
  const identity = await (await response).json();
  await expect(
    page.getByRole("button", { name: "Start microphone" })
  ).toBeEnabled();
  return identity;
}
async function record(page: Page, identity: any) {
  const response = await page.request.get("/api/sessions/" + identity.id, {
    headers: { Authorization: "Bearer " + identity.token },
  });
  return response.json();
}

test("real microphone worklet completes Pipecat turn and operator takes over context", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const identity = await create(page);
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(
    page.locator(".turn .pill").filter({ hasText: "completed" })
  ).toBeVisible({ timeout: 60000 });
  await page.getByRole("button", { name: "Stop microphone" }).click();
  const detail = await record(page, identity);
  expect(detail.turns[0].transcript.length).toBeGreaterThan(3);
  expect(detail.turns[0].reply.length).toBeGreaterThan(3);
  expect(detail.turns[0].timings.first_audio_ms).toBeGreaterThan(0);
  expect(detail.events.some((e: any) => e.kind === "utterance")).toBe(true);
  await page.screenshot({
    path: info.outputPath("conversation.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Request an operator" }).click();
  await expect(
    page.getByRole("heading", { name: "An operator can take over." })
  ).toBeVisible();
  await page.getByRole("button", { name: /Operator review/ }).click();
  await page
    .getByLabel("Operator key", { exact: true })
    .fill(config.VOICE_OPERATOR_KEY);
  await page.getByRole("button", { name: "Load conversations" }).click();
  await page
    .getByRole("button", { name: new RegExp(identity.id.slice(0, 8)) })
    .click();
  await expect(
    page
      .locator(".transcript p")
      .filter({ hasText: detail.turns[0].transcript })
  ).toBeVisible();
  await page.getByRole("button", { name: "Accept handoff" }).click();
  await expect(
    page.getByRole("button", { name: "Complete conversation" })
  ).toBeEnabled();
  await page.screenshot({
    path: info.outputPath("operator-handoff.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Complete conversation" }).click();
  await expect(
    page.getByRole("button", { name: "Accept handoff" })
  ).toBeDisabled();
  const final = await record(page, identity);
  expect(final.session.phase).toBe("closed");
  expect(errors).toEqual([]);
  await info.attach("actual-turn-and-handoff", {
    body: Buffer.from(JSON.stringify(final, null, 2)),
    contentType: "application/json",
  });
});

test("interruption flushes actual scheduled speech and reconnect requires consent", async ({
  page,
}, info) => {
  const identity = await create(page);
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(
    page.getByRole("heading", { name: "A response is playing." })
  ).toBeVisible({ timeout: 60000 });
  await page.getByRole("button", { name: "Interrupt response" }).click();
  await expect
    .poll(async () => (await record(page, identity)).turns[0].state)
    .toBe("cancelled");
  await page.getByRole("button", { name: "Reconnect", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Start microphone" })
  ).toBeEnabled();
  await expect(
    page.getByText("CURRENT TURN", { exact: true })
  ).not.toBeVisible();
  const detail = await record(page, identity);
  expect(detail.session.recording).toBe(0);
  expect(detail.session.connection).toBeGreaterThan(1);
  expect(
    detail.events.some(
      (e: any) => e.kind === "playback_stopped" && e.detail.interruption_ms >= 0
    )
  ).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: info.outputPath("mobile-reconnected.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth
    )
  ).toBe(true);
  await info.attach("interruption-and-reconnect", {
    body: Buffer.from(JSON.stringify(detail, null, 2)),
    contentType: "application/json",
  });
});

test("actual delayed provider stage fails within its deadline and reports a durable error", async ({
  page,
}, info) => {
  const identity = await create(page);
  await page.getByText("Reliability scenarios", { exact: true }).click();
  await page.getByLabel("Delay the next provider stage").selectOption("model");
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("alert")).toContainText("provider timeout", {
    timeout: 45000,
  });
  await page.getByRole("button", { name: "Stop microphone" }).click();
  const detail = await record(page, identity);
  expect(detail.turns[0].state).toBe("failed");
  expect(detail.turns[0].error_code).toBe("provider_timeout");
  expect(detail.turns[0].reply).toBe("");
  await info.attach("actual-provider-timeout", {
    body: Buffer.from(JSON.stringify(detail, null, 2)),
    contentType: "application/json",
  });
});
