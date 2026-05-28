import fs from 'node:fs';
import { chromium } from 'playwright';

const baseURL = process.env.RAGRIG_CONSOLE_E2E_BASE_URL;
const outputPath = process.env.RAGRIG_CONSOLE_E2E_OUTPUT;
const filePaths = JSON.parse(process.env.RAGRIG_CONSOLE_E2E_FILES || '[]');
const headless = process.env.RAGRIG_CONSOLE_E2E_HEADLESS !== '0';
const browserChannel = process.env.RAGRIG_CONSOLE_E2E_BROWSER_CHANNEL || '';
const timeout = Number(process.env.RAGRIG_CONSOLE_E2E_TIMEOUT_MS || 30000);
const kbName = 'local-pilot-e2e';

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

async function fetchJson(page, path) {
  return page.evaluate(async (targetPath) => {
    const response = await fetch(targetPath);
    const body = await response.json().catch(async () => response.text());
    return { status: response.status, body };
  }, path);
}

async function waitForTask(page, taskId) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    const response = await fetchJson(page, `/tasks/${taskId}?include=pipeline_run`);
    assert(response.status === 200, `task status returned ${response.status}`);
    last = response.body;
    if (last.status === 'completed' || last.status === 'failed') return last;
    await page.waitForTimeout(500);
  }
  throw new Error(`task did not finish before timeout: ${JSON.stringify(last)}`);
}

function apiPath(response) {
  return decodeURIComponent(new URL(response.url()).pathname);
}

async function openRoute(page, path) {
  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, path);
  await page.waitForTimeout(100);
}

async function run() {
  assert(baseURL, 'RAGRIG_CONSOLE_E2E_BASE_URL is required');
  assert(filePaths.length >= 3, 'RAGRIG_CONSOLE_E2E_FILES must include md/pdf/docx fixtures');

  const launchOptions = browserChannel ? { headless, channel: browserChannel } : { headless };
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });

  try {
    await page.goto(`${baseURL}/`, { waitUntil: 'networkidle', timeout });
    await waitForText(page, 'body', /RAGRig|Overview|System/i);

    await openRoute(page, '/knowledge-bases');
    await page.locator('#knowledge-base-name').waitFor({ timeout });
    await page.fill('#knowledge-base-name', kbName);
    const createResponsePromise = page.waitForResponse(
      (response) => apiPath(response) === '/knowledge-bases' && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('#knowledge-base-create');
    const createResponse = await createResponsePromise;
    assert([200, 201].includes(createResponse.status()), `create KB returned ${createResponse.status()}`);
    const createdKb = await createResponse.json();
    assert(createdKb.id, `create KB did not return an id: ${JSON.stringify(createdKb)}`);
    await waitForText(page, 'body', /local-pilot-e2e/);

    await openRoute(page, '/upload');
    await page.locator('#upload-kb-select').waitFor({ timeout });
    await page.selectOption('#upload-kb-select', kbName);
    await page.setInputFiles('#upload-file-input', filePaths);
    await waitForText(page, 'body', /pilot-console-e2e\.md/);
    await waitForText(page, 'body', /pilot-console-e2e\.pdf/);
    await waitForText(page, 'body', /pilot-console-e2e\.docx/);

    const uploadResponsePromise = page.waitForResponse(
      (response) => apiPath(response) === `/knowledge-bases/${kbName}/upload` && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('#upload-submit');
    const uploadResponse = await uploadResponsePromise;
    assert(uploadResponse.status() === 202, `upload returned ${uploadResponse.status()}`);
    const upload = await uploadResponse.json();
    assert(upload.accepted_files >= 3, `expected all files accepted: ${JSON.stringify(upload)}`);
    assert(upload.rejected_files === 0, `expected no upload rejections: ${JSON.stringify(upload)}`);
    await waitForText(page, '#upload-result', /Accepted/);

    const task = await waitForTask(page, upload.task_id);
    assert(task.status === 'completed', `upload task did not complete: ${JSON.stringify(task)}`);
    assert(task.pipeline_run?.status === 'completed', `pipeline run did not complete: ${JSON.stringify(task)}`);
    const indexing = task.result?.indexing || {};
    assert(indexing.indexed_count >= 3, `expected all files indexed: ${JSON.stringify(task)}`);
    assert(indexing.failed_count === 0, `expected no indexing failures: ${JSON.stringify(task)}`);
    assert(indexing.chunk_count >= 3, `expected chunks to be created: ${JSON.stringify(task)}`);
    await waitForText(page, '#upload-task-progress', /completed/);

    await openRoute(page, '/documents');
    await waitForText(page, 'body', /pilot-console-e2e\.md/);
    await waitForText(page, 'body', /pilot-console-e2e\.pdf/);
    await waitForText(page, 'body', /pilot-console-e2e\.docx/);

    const question = 'What does the Local Pilot E2E verify about grounded answers and citations?';
    await openRoute(page, '/retrieval-lab');
    await page.locator('#retrieval-lab-kb-select').waitFor({ timeout });
    await page.selectOption('#retrieval-lab-kb-select', createdKb.id);
    await page.selectOption('#retrieval-lab-mode', 'dense');
    await page.fill('#retrieval-lab-query', question);
    const searchResponsePromise = page.waitForResponse(
      (response) => apiPath(response) === '/retrieval/search' && response.request().method() === 'POST',
      { timeout },
    );
    await page.getByRole('button', { name: 'Search' }).click();
    const searchResponse = await searchResponsePromise;
    assert(searchResponse.status() === 200, `search returned ${searchResponse.status()}`);
    const search = await searchResponse.json();
    assert(search.total_results >= 1, `search returned no results: ${JSON.stringify(search)}`);
    await waitForText(page, '#retrieval-lab-results', /pilot-console-e2e/);
    const retrievalResultsText = await textContent(page, '#retrieval-lab-results');

    await openRoute(page, '/answer-gen');
    await page.locator('#answer-kb-select').waitFor({ timeout });
    await page.selectOption('#answer-kb-select', kbName);
    await page.selectOption('#answer-mode-select', 'dense');
    await page.selectOption('#answer-retrieval-provider', 'deterministic-local');
    await page.fill('#answer-retrieval-model', '');
    await page.selectOption('#answer-provider', 'deterministic-local');
    await page.fill('#answer-model', '');
    await page.fill('#answer-query', question);
    const answerResponsePromise = page.waitForResponse(
      (response) => apiPath(response) === '/retrieval/answer' && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('#answer-submit');
    const answerResponse = await answerResponsePromise;
    assert(answerResponse.status() === 200, `answer returned ${answerResponse.status()}`);
    const answer = await answerResponse.json();
    assert(answer.grounding_status === 'grounded', `answer was not grounded: ${JSON.stringify(answer)}`);
    assert((answer.citations || []).length >= 1, `answer returned no citations: ${JSON.stringify(answer)}`);
    assert((answer.evidence_chunks || []).length >= 1, `answer returned no evidence chunks: ${JSON.stringify(answer)}`);
    await waitForText(page, '#answer-result', /grounded/);
    await waitForText(page, '#answer-result', /Citations/);

    assert(browserErrors.length === 0, `browser console errors: ${browserErrors.join('; ')}`);

    const result = {
      status: 'passed',
      base_url: baseURL,
      knowledge_base: {
        id: createdKb.id,
        name: kbName,
      },
      upload: {
        accepted_files: upload.accepted_files,
        indexed_count: indexing.indexed_count,
        chunk_count: indexing.chunk_count,
        failed_count: indexing.failed_count,
      },
      retrieval: {
        mode: search.mode || 'dense',
        total_results: search.total_results,
        top_document: search.results?.[0]?.document_uri || null,
      },
      answer: {
        grounding_status: answer.grounding_status,
        citation_count: answer.citations.length,
        evidence_chunk_count: answer.evidence_chunks.length,
        provider: answer.provider,
        model: answer.model,
      },
      ui: {
        retrieval_results: retrievalResultsText,
        answer_result: await textContent(page, '#answer-result'),
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
