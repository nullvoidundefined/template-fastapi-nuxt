/**
 * Visual regression for every Storybook story (spec: B-39).
 *
 * The story list comes from Storybook's own index rather than a hand-kept list, so a new story is
 * snapshotted the moment it exists, and a changed rendering without an updated baseline fails.
 */
import { test, expect, request as playwrightRequest } from '@playwright/test';

type StoryIndexEntry = { id: string; type: string };

const storybookUrl = process.env.STORYBOOK_URL ?? '';

/** Return every story id Storybook indexes. */
async function readStoryIds(): Promise<string[]> {
    const indexClient = await playwrightRequest.newContext({ baseURL: storybookUrl });
    const index = (await (await indexClient.get('/index.json')).json()) as {
        entries: Record<string, StoryIndexEntry>;
    };
    await indexClient.dispose();
    return Object.values(index.entries)
        .filter((entry) => entry.type === 'story')
        .map((entry) => entry.id);
}

// Storybook's dev server compiles each story on first load, which is slow on a cold start.
const ALL_STORIES_TIMEOUT_MS = 300_000;

test('every story matches its baseline', async ({ page }) => {
    test.setTimeout(ALL_STORIES_TIMEOUT_MS);
    const storyIds = await readStoryIds();
    expect(storyIds.length).toBeGreaterThan(0);
    for (const storyId of storyIds) {
        await page.goto(`/iframe.html?id=${storyId}&viewMode=story`);
        // Storybook adds this class once the story has rendered. The viewport is captured rather
        // than the root element, because Modal and Toast render into portals outside the root.
        await page.locator('body.sb-show-main').waitFor({ state: 'attached' });
        await page.evaluate(() => document.fonts.ready);
        await expect.soft(page).toHaveScreenshot(`${storyId}.png`);
    }
});
