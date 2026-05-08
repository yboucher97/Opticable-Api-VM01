import { rm } from "node:fs/promises";
import type { BrowserContext, Page } from "playwright";
import { chromium } from "playwright";

import { browserProfileDir, ensureRuntimeDirs } from "../runtime/paths";
import type { OmadaPlan } from "../config/schema";
import { clickFirstVisible, fillFirstVisible, findFirstVisible } from "./locators";

let loginContext: BrowserContext | null = null;
let loginClosedPromise: Promise<void> | null = null;
type ControllerSettings = OmadaPlan["controller"];

export interface OmadaSessionHandle {
  context: BrowserContext;
  page: Page;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
}

function hasInteractiveDisplay(): boolean {
  if (process.platform !== "linux") {
    return true;
  }

  return Boolean(process.env.DISPLAY || process.env.WAYLAND_DISPLAY);
}

function resolveCloudAccount(controller: ControllerSettings): ControllerSettings["cloudAccount"] | undefined {
  if (controller.cloudAccount) {
    return controller.cloudAccount;
  }

  const email = process.env.OMADA_SITE_CREATOR_CLOUD_EMAIL?.trim();
  const password = process.env.OMADA_SITE_CREATOR_CLOUD_PASSWORD;
  if (!email || !password) {
    return undefined;
  }

  return {
    email,
    password,
  };
}

function buildOptions(
  controller: ControllerSettings,
  forceHeaded: boolean,
): Parameters<typeof chromium.launchPersistentContext>[1] {
  const args = forceHeaded ? ["--start-maximized"] : [];
  if (process.platform === "linux") {
    args.push(
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-background-networking",
      "--disable-renderer-backgrounding",
      "--disable-software-rasterizer",
    );
  }

  const options: Parameters<typeof chromium.launchPersistentContext>[1] = {
    headless: forceHeaded ? false : controller.headless,
    viewport: forceHeaded ? null : { width: 1366, height: 900 },
    args,
  };

  if (controller.browserChannel !== "chromium") {
    options.channel = controller.browserChannel;
  }

  return options;
}

async function navigateToOrgManager(page: Page, controller: ControllerSettings): Promise<void> {
  await page.goto(`${normalizeBaseUrl(controller.baseUrl)}#orgManager`, { waitUntil: "domcontentloaded" });
}

async function readLoginError(page: Page): Promise<string | null> {
  const errorLocator = await findFirstVisible(page, [
    (root) => root.locator(".el-form-item__error"),
    (root) => root.locator(".el-message__content"),
    (root) => root.locator(".error-text,.error-msg,.tips-error"),
    (root) => root.getByText(/incorrect|invalid|failed|expired|required/i),
  ], 1500);

  if (!errorLocator) {
    return null;
  }

  const text = (await errorLocator.innerText().catch(() => "")).trim();
  return text.length > 0 ? text : null;
}

async function dismissPostLoginPrompts(page: Page): Promise<void> {
  const agreeButton = await findFirstVisible(page, [
    (root) => root.getByRole("button", { name: /^Agree$/i }),
    (root) => root.getByRole("link", { name: /^Agree$/i }),
    (root) => root.getByText(/^Agree$/i),
  ], 1200);

  if (agreeButton) {
    await agreeButton.click().catch(() => undefined);
    await page.waitForTimeout(500);
  }

  const okButton = await findFirstVisible(page, [
    (root) => root.getByRole("button", { name: /^OK$/i }),
    (root) => root.getByText(/^OK$/i),
  ], 1200);

  if (okButton) {
    await okButton.click().catch(() => undefined);
    await page.waitForTimeout(500);
  }
}

async function waitForLoginRedirect(page: Page, timeoutMs = 90000): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const currentUrl = page.url();
    if (!currentUrl.includes("id.tplinkcloud.com") && !(await isCloudLoginPage(page))) {
      await dismissPostLoginPrompts(page);
      return true;
    }

    const errorText = await readLoginError(page);
    if (errorText) {
      throw new Error(`Automatic TP-Link cloud login failed: ${errorText}`);
    }

    await page.waitForTimeout(1000);
  }

  return false;
}

export async function isCloudLoginPage(page: Page): Promise<boolean> {
  if (page.url().includes("id.tplinkcloud.com")) {
    return true;
  }

  const emailInput = await findFirstVisible(page, [
    (root) => root.locator("#form_item_email"),
    (root) => root.getByPlaceholder(/Email/i),
    (root) => root.locator("input[type='text']"),
  ], 700);

  if (!emailInput) {
    return false;
  }

  const passwordInput = await findFirstVisible(page, [
    (root) => root.locator("#form_item_password"),
    (root) => root.getByPlaceholder(/Password/i),
    (root) => root.locator("input[type='password']"),
  ], 700);

  if (!passwordInput) {
    return false;
  }

  const signInButton = await findFirstVisible(page, [
    (root) => root.getByRole("button", { name: /^Sign In$/i }),
    (root) => root.getByText(/^Sign In$/i),
    (root) => root.locator("a").filter({ hasText: /^Sign In$/i }),
  ], 700);

  return Boolean(signInButton);
}

async function attemptAutomaticCloudLogin(page: Page, controller: ControllerSettings): Promise<boolean> {
  const cloudAccount = resolveCloudAccount(controller);
  if (!cloudAccount) {
    return false;
  }

  if (!page.url().includes("id.tplinkcloud.com") && !(await isCloudLoginPage(page))) {
    return true;
  }

  await page.waitForLoadState("domcontentloaded", { timeout: 15000 }).catch(() => undefined);
  await page.waitForTimeout(1000);

  await fillFirstVisible(page, "TP-Link cloud email", cloudAccount.email, [
    (root) => root.locator("#form_item_email"),
    (root) => root.getByPlaceholder(/Email/i),
    (root) => root.locator("input[type='text']"),
  ], 5000);

  await fillFirstVisible(page, "TP-Link cloud password", cloudAccount.password, [
    (root) => root.locator("#form_item_password"),
    (root) => root.getByPlaceholder(/Password/i),
    (root) => root.locator("input[type='password']"),
  ], 5000);

  await clickFirstVisible(page, "TP-Link Sign In", [
    (root) => root.getByRole("button", { name: /^Sign In$/i }),
    (root) => root.getByText(/^Sign In$/i),
    (root) => root.locator("a").filter({ hasText: /^Sign In$/i }),
  ], 5000);

  let redirectSucceeded = await waitForLoginRedirect(page, 45000);
  if (!redirectSucceeded) {
    await page.locator("#form_item_password").press("Enter", { timeout: 5000 }).catch(() => undefined);
    redirectSucceeded = await waitForLoginRedirect(page, 45000);
  }

  if (redirectSucceeded) {
    return true;
  }

  const errorText = await readLoginError(page);
  throw new Error(
    errorText
      ? `Automatic TP-Link cloud login failed: ${errorText}`
      : "Automatic TP-Link cloud login failed. The login page stayed open after submitting credentials.",
  );
}

export async function recoverCloudLogin(page: Page, controller: ControllerSettings): Promise<boolean> {
  if (!page.url().includes("id.tplinkcloud.com") && !(await isCloudLoginPage(page))) {
    return true;
  }

  const loggedIn = await attemptAutomaticCloudLogin(page, controller);
  if (!loggedIn) {
    return false;
  }

  await navigateToOrgManager(page, controller);
  await page.waitForTimeout(5000);
  if (page.url().includes("id.tplinkcloud.com") || await isCloudLoginPage(page)) {
    return false;
  }
  return true;
}

export async function launchLoginBrowser(controller: ControllerSettings): Promise<{ message: string; alreadyOpen: boolean; closePromise: Promise<void>; }> {
  ensureRuntimeDirs();

  if (loginContext) {
    return {
      message: "Login browser is already open. Complete login there and close it before starting a run.",
      alreadyOpen: true,
      closePromise: loginClosedPromise ?? Promise.resolve(),
    };
  }

  if (!hasInteractiveDisplay()) {
    throw new Error("Interactive login requires a display on Linux. On a VPS, set OMADA_SITE_CREATOR_CLOUD_EMAIL and OMADA_SITE_CREATOR_CLOUD_PASSWORD and use the webhook/server flow instead.");
  }

  loginContext = await chromium.launchPersistentContext(browserProfileDir, buildOptions(controller, true));
  const page = loginContext.pages()[0] ?? await loginContext.newPage();
  await navigateToOrgManager(page, controller);

  loginClosedPromise = new Promise<void>((resolve) => {
    const done = () => {
      loginContext = null;
      loginClosedPromise = null;
      resolve();
    };

    loginContext?.once("close", done);
    loginContext?.browser()?.once("disconnected", done);
  });

  return {
    message: "Login browser opened. Log in to Omada, wait until the org list loads, then close that browser window.",
    alreadyOpen: false,
    closePromise: loginClosedPromise,
  };
}

export async function withAuthenticatedSession<T>(
  controller: ControllerSettings,
  work: (handle: OmadaSessionHandle) => Promise<T>,
): Promise<T> {
  ensureRuntimeDirs();

  if (loginContext) {
    throw new Error("Close the interactive login browser before starting a run.");
  }

  const useEphemeralProfile = false;
  const profileDir = browserProfileDir;
  const context = await chromium.launchPersistentContext(profileDir, buildOptions(controller, false));

  try {
    const page = context.pages()[0] ?? await context.newPage();
    await navigateToOrgManager(page, controller);

    if (page.url().includes("id.tplinkcloud.com") || await isCloudLoginPage(page)) {
      const loggedIn = await recoverCloudLogin(page, controller);
      if (!loggedIn) {
        throw new Error("Stored session is not logged in. Open the login browser first, or set OMADA_SITE_CREATOR_CLOUD_EMAIL and OMADA_SITE_CREATOR_CLOUD_PASSWORD for automatic login.");
      }
    }

    return await work({ context, page });
  } finally {
    await context.close();
    if (useEphemeralProfile) {
      await rm(profileDir, { recursive: true, force: true }).catch(() => undefined);
    }
  }
}
