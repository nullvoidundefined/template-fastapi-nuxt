/**
 * The smoke suite (spec B-28, amended 2026-09-24; workspace convention "smoke verifies all
 * services start and respond"): each service's health probe answers, and the landing page renders
 * through the web server. It reads no data and writes none, so it is safe against any deployment.
 */
import { test, expect } from '@playwright/test';

const apiBaseUrl = process.env.SMOKE_API_URL ?? '';
const workerBaseUrl = process.env.SMOKE_WORKER_URL ?? '';

test('the web server answers GET /api/health', async ({ request }) => {
    const response = await request.get('/api/health');

    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok' });
});

test('the API answers GET /health', async ({ request }) => {
    const response = await request.get(`${apiBaseUrl}/health`);

    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok' });
});

test('the API is ready, with its database connected', async ({ request }) => {
    const response = await request.get(`${apiBaseUrl}/health/ready`);

    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ status: 'ok' });
});

test('the worker is ready, with Postgres and Redis reachable', async ({ request }) => {
    const response = await request.get(`${workerBaseUrl}/health/ready`);

    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ status: 'ok' });
});

test('the landing page renders its one heading', async ({ page }) => {
    const response = await page.goto('/');

    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
});
