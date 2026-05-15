import fs from 'node:fs';
import { chromium } from 'playwright';

const baseURL = process.env.RAGRIG_CONSOLE_E2E_BASE_URL;
const outputPath = process.env.RAGRIG_CONSOLE_E2E_OUTPUT;
const filePaths = JSON.parse(process.env.RAGRIG_CONSOLE_E2E_FILES || '[]');
const failureFilePath = process.env.RAGRIG_CONSOLE_E2E_FAILURE_FILE;
const headless = process.env.RAGRIG_CONSOLE_E2E_HEADLESS !== '0';
const browserChannel = process.env.RAGRIG_CONSOLE_E2E_BROWSER_CHANNEL || '';
const timeout = Number(process.env.RAGRIG_CONSOLE_E2E_TIMEOUT_MS || 30000);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function textContent(page, selector) {
  return (await page.locator(selector).textContent({ timeout })) || '';
}

async function waitForText(page, selector, pattern) {
  await page.waitForFunction(
    ({ selector: targetSelector, source, flags }) => {
      const text = document.querySelector(targetSelector)?.textContent || '';
      return new RegExp(source, flags).test(text);
    },
    { selector, source: pattern.source, flags: pattern.flags },
    { timeout },
  );
}

async function run() {
  assert(baseURL, 'RAGRIG_CONSOLE_E2E_BASE_URL is required');
  assert(filePaths.length >= 3, 'RAGRIG_CONSOLE_E2E_FILES must include md/pdf/docx fixtures');
  assert(failureFilePath, 'RAGRIG_CONSOLE_E2E_FAILURE_FILE is required');

  const launchOptions = browserChannel ? { headless, channel: browserChannel } : { headless };
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });

  try {
    await page.goto(`${baseURL}/console`, { waitUntil: 'networkidle', timeout });
    await page.locator('[data-local-pilot-wizard]').waitFor({ timeout });
    await waitForText(page, '[data-local-pilot-wizard]', /Local Pilot/);

    await page.fill('#pilot-kb-name', 'local-pilot-e2e');
    await page.selectOption('#pilot-provider', 'deterministic-local');

    await page.click('#pilot-model-health');
    await waitForText(page, '#pilot-output', /"status": "healthy"/);

    await page.click('#pilot-answer-smoke');
    await waitForText(page, '#pilot-output', /"detail"/);

    await page.fill('#pilot-kb-name', 'local-pilot-e2e-failure');
    await page.setInputFiles('#pilot-file-input', failureFilePath);
    await waitForText(page, '#pilot-file-list', /pilot-console-e2e-bad\.txt/);
    const failureUploadResponsePromise = page.waitForResponse(
      (response) => response.url().includes('/knowledge-bases/local-pilot-e2e-failure/upload')
        && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('#pilot-upload-files');
    const failureUploadResponse = await failureUploadResponsePromise;
    assert(failureUploadResponse.status() === 202, `failure upload returned ${failureUploadResponse.status()}`);
    const failureUpload = await failureUploadResponse.json();
    assert(failureUpload.ingestion?.failed_count === 1, `expected one parser failure: ${JSON.stringify(failureUpload)}`);
    await waitForText(page, '#pilot-run-summary', /Action required/);
    await waitForText(page, '#pilot-run-summary', /pilot-console-e2e-bad\.txt/);
    await waitForText(page, '#pilot-run-summary', /failure_reason|error:/);
    await page.locator('[data-pilot-retry-run]').waitFor({ timeout });

    const retryResponsePromise = page.waitForResponse(
      (response) => response.url().includes('/pipeline-runs/')
        && response.url().includes('/retry')
        && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('[data-pilot-retry-run]');
    const retryResponse = await retryResponsePromise;
    assert(retryResponse.status() === 200, `retry returned ${retryResponse.status()}`);
    const retry = await retryResponse.json();
    assert(retry.failed === 1, `expected retry to preserve parser failure, not lose source file: ${JSON.stringify(retry)}`);
    assert(!JSON.stringify(retry).toLowerCase().includes('file not found'), `retry lost upload source file: ${JSON.stringify(retry)}`);
    await waitForText(page, '#pilot-output', /"failed": 1/);

    await page.fill('#pilot-kb-name', 'local-pilot-e2e');
    await page.setInputFiles('#pilot-file-input', filePaths);
    await waitForText(page, '#pilot-file-list', /pilot-console-e2e\.md/);
    await waitForText(page, '#pilot-file-list', /pilot-console-e2e\.pdf/);
    await waitForText(page, '#pilot-file-list', /pilot-console-e2e\.docx/);

    const uploadResponsePromise = page.waitForResponse(
      (response) => response.url().includes('/knowledge-bases/local-pilot-e2e/upload')
        && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('#pilot-upload-files');
    const uploadResponse = await uploadResponsePromise;
    assert(uploadResponse.status() === 202, `upload returned ${uploadResponse.status()}`);
    const upload = await uploadResponse.json();
    assert(upload.indexing?.indexed_count >= 3, `expected all files indexed: ${JSON.stringify(upload)}`);
    assert(upload.indexing?.failed_count === 0, `expected no indexing failures: ${JSON.stringify(upload)}`);

    await waitForText(page, '#pilot-run-summary', /Latest run/);
    await waitForText(page, '#pilot-run-summary', /pilot-console-e2e\.md/);
    await waitForText(page, '#pilot-run-summary', /pilot-console-e2e\.pdf/);
    await waitForText(page, '#pilot-run-summary', /pilot-console-e2e\.docx/);
    await waitForText(page, '#pilot-chunk-preview', /Chunk 0/);

    const question = 'What does the Local Pilot E2E verify about grounded answers and citations?';
    await page.fill('#pilot-question', question);
    const answerResponsePromise = page.waitForResponse(
      (response) => response.url().includes('/retrieval/answer')
        && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('#pilot-run-answer');
    const answerResponse = await answerResponsePromise;
    assert(answerResponse.status() === 200, `answer returned ${answerResponse.status()}`);
    const answer = await answerResponse.json();
    assert(answer.grounding_status === 'grounded', `answer was not grounded: ${JSON.stringify(answer)}`);
    assert((answer.citations || []).length >= 1, `answer returned no citations: ${JSON.stringify(answer)}`);
    assert((answer.evidence_chunks || []).length >= 1, `answer returned no evidence chunks: ${JSON.stringify(answer)}`);

    await waitForText(page, '#pilot-answer-result', /Answer/);
    await waitForText(page, '#pilot-answer-result', /grounded/);
    await waitForText(page, '#pilot-answer-result', /Provider: deterministic-local/);

    assert(browserErrors.length === 0, `browser console errors: ${browserErrors.join('; ')}`);

    const result = {
      status: 'passed',
      base_url: baseURL,
      upload: {
        indexed_count: upload.indexing.indexed_count,
        chunk_count: upload.indexing.chunk_count,
        failed_count: upload.indexing.failed_count,
      },
      failure_status: {
        ingestion_failed_count: failureUpload.ingestion.failed_count,
        retry_failed_count: retry.failed,
      },
      answer: {
        grounding_status: answer.grounding_status,
        citation_count: answer.citations.length,
        evidence_chunk_count: answer.evidence_chunks.length,
        provider: answer.provider,
        model: answer.model,
      },
      ui: {
        run_summary: await textContent(page, '#pilot-run-summary'),
        chunk_preview: await textContent(page, '#pilot-chunk-preview'),
        answer_result: await textContent(page, '#pilot-answer-result'),
      },
    };
    if (outputPath) {
      fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
    }
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
