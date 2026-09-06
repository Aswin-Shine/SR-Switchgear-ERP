import { type Page, expect, test } from "@playwright/test";

/**
 * One journey, exercising the system's central claim: an enquiry splits into lines that
 * move independently, and moving one does not move the other.
 *
 *   log in → create an enquiry with two job lines → move line 1 to Quotation
 *   → upload a quotation revision and mark it sent
 *   → assert line 2 is still at Enquiry and the board shows them in different columns
 *
 * It needs the real stack (Django + PostgreSQL + the built SPA):
 *
 *   docker compose up -d db && python manage.py migrate && python manage.py bootstrap_admin
 *   npm --prefix frontend run build && python manage.py collectstatic --noinput
 *   E2E_BASE_URL=http://127.0.0.1:8000 npx playwright test
 *
 * Without E2E_BASE_URL it skips: a journey that cannot reach a server proves nothing, and
 * a red suite nobody can fix locally gets ignored.
 */
const BASE_URL = process.env.E2E_BASE_URL;
const USERNAME = process.env.E2E_USERNAME ?? "sales";
const PASSWORD = process.env.E2E_PASSWORD ?? "sales-password";

const FIRST_LINE = "LT panel 1600A, form 4b";
const SECOND_LINE = "Spare feeder modules";

test.skip(!BASE_URL, "Set E2E_BASE_URL to run the journey against a running stack.");

async function signIn(page: Page): Promise<void> {
  await page.goto("/login/");
  await page.getByLabel(/username/i).fill(USERNAME);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /log in|sign in/i }).click();
  await page.waitForURL(/\/app/);
}

test("an enquiry splits into lines that move independently", async ({ page }) => {
  await signIn(page);

  // --- create the enquiry, with two lines -----------------------------------
  await page.goto("/app/job-cards/new");

  await page.getByLabel("Client").fill("");
  await page.getByLabel("Client").type("a");
  await page.getByRole("option").first().click();

  await page.getByLabel(/^Title/).fill("Playwright journey enquiry");
  await page
    .getByLabel(/^Description/)
    .first()
    .fill(FIRST_LINE);

  await page.getByRole("button", { name: "Add line" }).click();
  await page
    .getByLabel(/^Description/)
    .nth(1)
    .fill(SECOND_LINE);

  await page.getByRole("button", { name: "Create enquiry" }).click();

  await expect(page).toHaveURL(/\/app\/job-cards\/[0-9a-f-]+$/);
  const jobNo = (await page.locator(".mono").first().innerText()).trim();

  const firstRow = page.getByRole("row", { name: new RegExp(FIRST_LINE) });
  const secondRow = page.getByRole("row", { name: new RegExp(SECOND_LINE) });
  await expect(firstRow).toBeVisible();
  await expect(secondRow).toBeVisible();

  // --- move line 1 only -----------------------------------------------------
  await firstRow.getByRole("button", { name: /Move to Quotation/i }).click();
  await page.getByRole("button", { name: "Confirm move" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();

  await expect(firstRow.getByText("Quotation")).toBeVisible();
  await expect(secondRow.getByText("Enquiry")).toBeVisible();

  // --- quote the line that moved -------------------------------------------
  await page.getByRole("button", { name: "Upload revision" }).click();
  await page.getByLabel("Quotation PDF").setInputFiles({
    name: "quotation.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 journey"),
  });
  await page.getByLabel(/Quoted amount/).fill("1845000.00");
  await page.getByRole("button", { name: "Upload revision" }).last().click();

  await expect(page.getByText("Rev 1")).toBeVisible();
  await page.getByRole("button", { name: "Mark sent" }).click();
  await expect(page.getByText("Sent")).toBeVisible();

  // --- the board shows the split -------------------------------------------
  await page.goto(`/app/board?q=${encodeURIComponent(jobNo)}`);

  const quotationColumn = page.getByRole("region", { name: /^Quotation/ });
  const enquiryColumn = page.getByRole("region", { name: /^Enquiry/ });

  await expect(quotationColumn.getByText(FIRST_LINE)).toBeVisible();
  await expect(enquiryColumn.getByText(SECOND_LINE)).toBeVisible();
  await expect(quotationColumn.getByText(SECOND_LINE)).toHaveCount(0);
});
