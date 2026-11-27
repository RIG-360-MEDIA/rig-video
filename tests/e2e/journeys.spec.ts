import { expect, test, type Page } from "@playwright/test";

// What editors click every day, in a real browser against the real API. Seeded by serve.py.
const EMAIL = "e2e@rig.test";
const PASSWORD = "test password 1";

async function signIn(page: Page) {
  await page.goto("/signin");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).last().click();
  await expect(page).toHaveURL(/\/desk$/);
}

async function storyId(page: Page, headline: string): Promise<string> {
  const desk = await (await page.request.get("/api/desk")).json();
  const p = desk.projects.find((x: { headline: string }) => x.headline === headline);
  expect(p, `seeded story "${headline}"`).toBeTruthy();
  return p.id;
}

test("signed out, the desk sends you to sign in", async ({ page }) => {
  await page.goto("/desk");
  await expect(page).toHaveURL(/\/signin$/);
});

test("a wrong password is refused with a message", async ({ page }) => {
  await page.goto("/signin");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in", exact: true }).last().click();
  await expect(page.getByRole("alert")).toContainText("don't match");
  await expect(page).toHaveURL(/\/signin$/);
});

test("the desk shows today's picks, stories and videos ready to post", async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole("heading", { name: /Today's picks/ })).toBeVisible();
  await expect(page.getByText("Floods hit Kathmandu valley")).toBeVisible();
  await expect(page.getByText("Missile strike on Kharkiv grid")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Ready to post/ })).toBeVisible();
  await expect(page.getByText("Script stage story").first()).toBeVisible();
});

test("every story step opens", async ({ page }) => {
  await signIn(page);
  const script = await storyId(page, "Script stage story");
  await page.goto(`/story/${script}/script`);
  await expect(page.getByLabel("Beat 1 text")).toHaveValue("Beat 1 line.");
  const visuals = await storyId(page, "Visuals stage story");
  await page.goto(`/story/${visuals}/visuals`);
  await expect(page).toHaveURL(new RegExp(`/story/${visuals}/visuals$`));
  const review = await storyId(page, "Review stage story");
  await page.goto(`/story/${review}/review`);
  await expect(page).toHaveURL(new RegExp(`/story/${review}/review$`));
  await page.goto(`/story/${review}/render`);                      // not rendered yet: Render sends it back to Review
  await expect(page).toHaveURL(new RegExp(`/story/${review}/review$`));
});

test("a finished video opens on Render with Post, Remake and Discard", async ({ page }) => {
  await signIn(page);
  const id = await storyId(page, "Finished story to remake");
  await page.goto(`/story/${id}`);
  await expect(page).toHaveURL(new RegExp(`/story/${id}/render$`));
  await expect(page.getByRole("button", { name: "Remake" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Discard" })).toBeEnabled();
});

test("a public video cannot be remade or discarded", async ({ page }) => {
  await signIn(page);
  const id = await storyId(page, "Already public story");
  await page.goto(`/story/${id}/render`);
  await expect(page.getByRole("button", { name: "Remake" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Discard" })).toBeDisabled();
});

test("Remake, open it to change: back to Review without its video", async ({ page }) => {
  await signIn(page);
  const id = await storyId(page, "Finished story to remake");
  await page.goto(`/story/${id}/render`);
  await page.getByRole("button", { name: "Remake" }).click();
  await expect(page.getByRole("dialog")).toContainText("Awaiting approval");
  await page.getByRole("button", { name: "Open it to change" }).click();
  await expect(page).toHaveURL(new RegExp(`/story/${id}/review$`));
  const p = (await (await page.request.get("/api/desk")).json()).projects.find((x: { id: string }) => x.id === id);
  expect(p.stage).toBe("review");
  expect(p.final).toBeUndefined();
});

test("Discard: the video leaves the desk and the library", async ({ page }) => {
  await signIn(page);
  const id = await storyId(page, "Finished story to discard");
  await page.goto(`/story/${id}/render`);
  await page.getByRole("button", { name: "Discard" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Discard" }).click();
  await expect(page).toHaveURL(/\/desk$/);
  const desk = await (await page.request.get("/api/desk")).json();
  expect(desk.projects.map((x: { id: string }) => x.id)).not.toContain(id);
  expect(desk.library.map((x: { id: string }) => x.id)).not.toContain(`lib-${id}`);
});

test("the library lists finished videos; a public one cannot be remade from there", async ({ page }) => {
  await signIn(page);
  await page.goto("/library");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await page.getByText("Already public story").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Remake" })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Discard" })).toBeDisabled();
});

test("add your own pick: it waits on the desk for the daily run, and can be removed", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Add your own" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Link or article text").fill("https://example.com/news/dam-burst-floods-libyan-town");
  await dialog.getByRole("button", { name: "Add to today's picks" }).click();
  const card = page.getByRole("article").filter({ hasText: "dam burst floods libyan town" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Yours");
  await expect(card).toContainText("Starts with the daily run");
  await card.getByRole("button", { name: "Remove" }).click();
  await expect(card).toHaveCount(0);
  const desk = await (await page.request.get("/api/desk")).json();
  expect(desk.picks.filter((p: { own?: boolean }) => p.own)).toHaveLength(0);
});

test("a too-short own pick is refused with a message", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Add your own" }).click();
  await page.getByRole("dialog").getByLabel("Link or article text").fill("Too short to be an article.");
  await page.getByRole("dialog").getByRole("button", { name: "Add to today's picks" }).click();
  await expect(page.getByText("too short to be an article")).toBeVisible();
});

test("sign out ends the session", async ({ page }) => {
  await signIn(page);
  await page.request.post("/api/logout");
  expect((await page.request.get("/api/desk")).status()).toBe(401);
});
