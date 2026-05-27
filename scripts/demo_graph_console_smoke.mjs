import { chromium } from 'playwright';

const baseURL = process.env.RAGRIG_GRAPH_CONSOLE_SMOKE_BASE_URL;
const knowledgeBaseName = process.env.RAGRIG_GRAPH_CONSOLE_SMOKE_KNOWLEDGE_BASE;
const headless = process.env.RAGRIG_GRAPH_CONSOLE_SMOKE_HEADLESS !== '0';
const browserChannel = process.env.RAGRIG_GRAPH_CONSOLE_SMOKE_BROWSER_CHANNEL || '';
const timeout = Number(process.env.RAGRIG_GRAPH_CONSOLE_SMOKE_TIMEOUT_MS || 30000);

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

async function fetchJson(page, url, options = {}) {
  return page.evaluate(
    async ({ targetUrl, fetchOptions }) => {
      const response = await fetch(targetUrl, fetchOptions);
      const text = await response.text();
      let body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch (error) {
        body = { raw: text, parse_error: error.message };
      }
      return { ok: response.ok, status: response.status, body };
    },
    { targetUrl: url, fetchOptions: options },
  );
}

async function run() {
  assert(baseURL, 'RAGRIG_GRAPH_CONSOLE_SMOKE_BASE_URL is required');
  assert(knowledgeBaseName, 'RAGRIG_GRAPH_CONSOLE_SMOKE_KNOWLEDGE_BASE is required');

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
    await page.locator('#graph-explorer-panel').waitFor({ timeout });
    await page.locator('#retrieval-kb').waitFor({ timeout });
    await page.locator('#graph-kb').waitFor({ timeout });
    await waitForText(page, '#graph-explorer-panel', /Graph Explorer/);

    const kbResponse = await fetchJson(page, '/knowledge-bases');
    assert(kbResponse.ok, `knowledge-bases returned ${kbResponse.status}`);
    const kb = (kbResponse.body.items || []).find((item) => item.name === knowledgeBaseName);
    assert(kb, `knowledge base ${knowledgeBaseName} was not found`);

    await page.selectOption('#retrieval-kb', kb.name);
    await page.selectOption('#graph-kb', kb.id);

    const graphResponsePromise = page.waitForResponse(
      (response) => response.url().includes(`/knowledge-bases/${kb.id}/knowledge-graph`)
        && response.request().method() === 'GET',
      { timeout },
    );
    await page.click('#refresh-graph-explorer');
    const graphResponse = await graphResponsePromise;
    assert(graphResponse.status() === 200, `graph endpoint returned ${graphResponse.status()}`);
    const graph = await graphResponse.json();
    assert(graph.status === 'ready', `graph was not ready: ${JSON.stringify(graph)}`);
    assert((graph.stats?.entity_count || 0) >= 2, `expected graph entities: ${JSON.stringify(graph.stats)}`);
    assert((graph.stats?.relation_count || 0) >= 1, `expected graph relations: ${JSON.stringify(graph.stats)}`);
    assert((graph.stats?.claim_count || 0) >= 1, `expected graph claims: ${JSON.stringify(graph.stats)}`);
    await waitForText(page, '#graph-explorer-body', /Entities/);
    await waitForText(page, '#graph-explorer-body', /Relations/);
    await waitForText(page, '#graph-explorer-body', /Mark Incorrect/);

    const relation = (graph.relations || [])[0];
    assert(relation?.id, 'graph smoke requires at least one relation with an id');
    const feedbackButton = page.locator(
      `[data-kg-relation-feedback="${relation.id}"][data-feedback-verdict="incorrect"]`,
    ).first();
    await feedbackButton.waitFor({ timeout });
    const feedbackResponsePromise = page.waitForResponse(
      (response) => response.url().includes(`/knowledge-bases/${kb.id}/knowledge-graph/relations/${relation.id}/feedback`)
        && response.request().method() === 'POST',
      { timeout },
    );
    await feedbackButton.click();
    const feedbackResponse = await feedbackResponsePromise;
    assert(feedbackResponse.status() === 200, `feedback endpoint returned ${feedbackResponse.status()}`);
    const feedback = await feedbackResponse.json();
    assert(feedback.feedback_summary?.incorrect >= 1, `feedback was not recorded: ${JSON.stringify(feedback)}`);
    await waitForText(page, '#graph-explorer-body', /incorrect: 1/);

    const preferenceResponsePromise = page.waitForResponse(
      (response) => response.url().includes(`/knowledge-bases/${kb.id}/retrieval-preferences`)
        && response.request().method() === 'GET',
      { timeout },
    );
    await page.click('#load-retrieval-preference');
    const preferenceResponse = await preferenceResponsePromise;
    assert(preferenceResponse.status() === 200, `preference endpoint returned ${preferenceResponse.status()}`);
    const preference = await preferenceResponse.json();
    assert(preference.preferences?.mode === 'hybrid_graph', `expected hybrid_graph preference: ${JSON.stringify(preference)}`);
    await waitForText(page, '#retrieval-preference-status', /hybrid_graph/);
    assert(await page.locator('#retrieval-mode').inputValue() === 'hybrid_graph', 'mode select did not load hybrid_graph');

    const graphQuery = `${relation.subject} ${relation.object}`;
    await page.fill('#retrieval-query', graphQuery);
    await page.fill('#retrieval-top-k', '5');

    await page.click('#compare-retrieval');
    await waitForText(page, '#retrieval-compare-results', /Strategy Comparison/);
    await waitForText(page, '#retrieval-compare-results', /dense/);
    await waitForText(page, '#retrieval-compare-results', /graph/);
    await waitForText(page, '#retrieval-compare-results', /hybrid_graph/);

    const retrievalResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith('/retrieval/search')
        && response.request().method() === 'POST',
      { timeout },
    );
    await page.click('#run-retrieval');
    const retrievalResponse = await retrievalResponsePromise;
    assert(retrievalResponse.status() === 200, `retrieval endpoint returned ${retrievalResponse.status()}`);
    const retrieval = await retrievalResponse.json();
    assert(retrieval.total_results >= 1, `expected retrieval hits: ${JSON.stringify(retrieval)}`);
    const graphContext = retrieval.graph_context || {};
    assert((graphContext.matched_entities || []).length >= 1, `expected matched graph entities: ${JSON.stringify(graphContext)}`);
    assert((graphContext.diagnostics?.suppressed_relation_count || 0) >= 1, `expected suppressed relation after feedback: ${JSON.stringify(graphContext)}`);
    await waitForText(page, '#retrieval-results', /Graph Context/);
    await waitForText(page, '#retrieval-results', /Matched Entities/);

    assert(browserErrors.length === 0, `browser console errors: ${browserErrors.join('; ')}`);

    const result = {
      status: 'passed',
      base_url: baseURL,
      knowledge_base: {
        id: kb.id,
        name: kb.name,
      },
      graph: {
        status: graph.status,
        entity_count: graph.stats.entity_count,
        relation_count: graph.stats.relation_count,
        claim_count: graph.stats.claim_count,
        evidence_chunk_count: graph.stats.graph_evidence_chunk_count,
      },
      feedback: {
        relation_id: relation.id,
        verdict: feedback.feedback.verdict,
        incorrect_count: feedback.feedback_summary.incorrect,
      },
      retrieval: {
        preference_mode: preference.preferences.mode,
        query: graphQuery,
        total_results: retrieval.total_results,
        matched_entity_count: graphContext.matched_entities.length,
        relation_path_count: (graphContext.relation_paths || []).length,
        suppressed_relation_count: graphContext.diagnostics.suppressed_relation_count,
      },
      ui: {
        graph_status: await textContent(page, '#graph-explorer-status'),
        retrieval_preference_status: await textContent(page, '#retrieval-preference-status'),
        compare_results: await textContent(page, '#retrieval-compare-results'),
      },
    };
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
