import type { Frame, Locator, Page } from "playwright";

export type QueryRoot = Page | Frame | Locator;
export type LocatorFactory = (root: QueryRoot) => Locator;

export function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export async function findFirstVisible(
  root: QueryRoot,
  candidates: LocatorFactory[],
  timeoutMs = 1500,
): Promise<Locator | null> {
  for (const candidate of candidates) {
    const locator = candidate(root);

    try {
      const count = await withTimeout(locator.count(), timeoutMs, 0);

      for (let index = 0; index < Math.min(count, 8); index += 1) {
        const current = locator.nth(index);

        if (await current.isVisible({ timeout: timeoutMs })) {
          return current;
        }
      }
    } catch {
      // Try the next locator candidate.
    }
  }

  return null;
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((resolve) => {
        timeout = setTimeout(() => resolve(fallback), timeoutMs);
      }),
    ]);
  } finally {
    if (timeout) {
      clearTimeout(timeout);
    }
  }
}

export async function clickFirstVisible(
  root: QueryRoot,
  description: string,
  candidates: LocatorFactory[],
  timeoutMs = 1500,
): Promise<void> {
  const locator = await findFirstVisible(root, candidates, timeoutMs);

  if (!locator) {
    throw new Error(`${description} was not found in the current Omada page.`);
  }

  await locator.click({ timeout: Math.max(timeoutMs, 5000) });
}

export async function fillFirstVisible(
  root: QueryRoot,
  description: string,
  value: string,
  candidates: LocatorFactory[],
  timeoutMs = 1500,
): Promise<void> {
  const locator = await findFirstVisible(root, candidates, timeoutMs);

  if (!locator) {
    throw new Error(`${description} input was not found in the current Omada page.`);
  }

  const actionTimeout = Math.max(timeoutMs, 5000);
  try {
    await locator.fill("", { timeout: actionTimeout });
    await locator.fill(value, { timeout: actionTimeout });
  } catch (error) {
    await locator.evaluate((element, nextValue) => {
      if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) {
        throw new Error("Target element is not a text input.");
      }

      element.focus();
      element.value = String(nextValue);
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      element.blur();
    }, value).catch(() => {
      throw error;
    });
  }
}
