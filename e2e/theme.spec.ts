/**
 * End-to-end checks of the theme preference against the built Nuxt server (spec: B-37, slice 07).
 *
 * Three properties, each only observable in a real browser loading real server output. The server
 * never renders a theme attribute, because it cannot read localStorage. The inline boot script sets
 * `data-theme` before the app hydrates: the test blocks every Nuxt bundle, so the app never runs at
 * all, and the attribute can only have come from the script in the head. And a theme chosen through
 * the toggle survives a reload, both on <html> and in the toggle itself.
 */
import { test, expect } from '@playwright/test';

const webBaseUrl = process.env.WEB_BASE_URL ?? '';
const themeStorageKey = 'theme-preference';

test.describe('theme preference', () => {
    test('US-THEME-001: the server renders no data-theme attribute on <html> (B-37)', async ({
        request,
    }) => {
        const response = await request.get(`${webBaseUrl}/`);
        const html = await response.text();

        const htmlOpeningTag = html.match(/<html[^>]*>/)?.[0] ?? '';
        expect(htmlOpeningTag).toContain('lang="en"');
        expect(htmlOpeningTag).not.toContain('data-theme');
        expect(html).toContain(themeStorageKey);
    });

    test('US-THEME-001: the boot script sets the stored theme before the app hydrates (B-37)', async ({
        page,
    }) => {
        await page.addInitScript((storageKey) => {
            window.localStorage.setItem(storageKey, 'dark');
        }, themeStorageKey);
        await page.route('**/_nuxt/**', (route) => route.abort());

        await page.goto(`${webBaseUrl}/`, { waitUntil: 'domcontentloaded' });

        await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    });

    test('US-THEME-001: a theme chosen in the toggle survives a reload (B-37)', async ({
        page,
    }) => {
        await page.goto(`${webBaseUrl}/`);
        const themeToggle = page.getByRole('combobox', { name: 'Theme' });

        // Retried until it takes: a choice made before hydration finishes is overwritten by the
        // stored preference when the app mounts, which under a loaded CI runner happens often.
        await expect(async () => {
            await themeToggle.selectOption('dark');
            await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark', {
                timeout: 1000,
            });
        }).toPass();
        await page.reload();

        await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
        await expect(themeToggle).toHaveValue('dark');
    });
});
