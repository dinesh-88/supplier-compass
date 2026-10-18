import { expect, test } from "@playwright/test";

test("log in → filter → add 3 to compare → compare → ask (mock) → memo", async ({ page }) => {
  await page.goto("/");
  await page.fill('input[name="username"]', "jury");
  await page.fill('input[name="password"]', "jury-e2e");
  await page.click("button:has-text('Sign in')");

  // Fresh user: Upload page, load the challenge sample.
  await page.getByTestId("load-sample").click();
  await expect(page.getByTestId("formula")).toContainText("verified");
  await page.getByRole("link", { name: "Explore" }).click();

  // Filter: exposure list (top 10% spend and Critical).
  await expect(page.getByTestId("match-count")).toHaveText("10,000");
  await page.getByTestId("toggle-exposure").check();
  await expect(page.getByTestId("match-count")).toHaveText("44");

  // Add 3 to compare.
  const boxes = page.getByTestId("compare-checkbox");
  for (let i = 0; i < 3; i++) await boxes.nth(i).check();
  await expect(page.getByTestId("compare-count")).toHaveText("3");
  await page.getByTestId("open-compare").click();

  // Compare page.
  await expect(page.getByTestId("heatmap").locator("tbody tr")).toHaveCount(3);
  await expect(page.getByTestId("why-a-over-b")).toContainText("gap of");

  // Ask about these (mock LLM).
  await page.getByTestId("ask-about-these").click();
  await page.getByTestId("chat-input").fill("Why is the Total Risk Index of SUPP_00018 so high?");
  await page.getByTestId("chat-send").click();
  const answer = page.getByTestId("chat-answer").last();
  await expect(answer).toContainText("Mock LLM");
  await expect(answer).toContainText("Operational Resilience");
  await answer.getByTestId("how-i-got-this").locator("summary").click();
  await expect(answer.getByTestId("how-i-got-this")).toContainText("explain_index");
  await page.getByLabel("Close assistant").click();

  // Generate the shortlist memo.
  await page.getByTestId("generate-memo").click();
  await page.getByTestId("memo-generate").click();
  const memo = page.getByTestId("memo-preview");
  await expect(memo).toContainText("Ranked shortlist");
  await expect(memo).toContainText("Risks to mitigate");
  const download = page.waitForEvent("download");
  await page.getByTestId("memo-md").click();
  expect((await download).suggestedFilename()).toBe("Supplier-shortlist-memo.md");
});
