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
    await page.goto(`${baseURL}/knowledge-map`, { waitUntil: 'domcontentloaded', timeout });
    await waitForText(page, 'main', /Knowledge Map/);
    await waitForText(page, 'main', /Relation explorer/);
    await waitForText(page, 'main', /Retrieval preferences/);
    await page.getByRole('button', { name: 'Hide from retrieval' }).click();
    await waitForText(page, 'main', /Hidden rel-/);
    const knowledgeMapTitle = await textContent(page, 'h1');

    const kbResponse = await fetchJson(page, '/knowledge-bases');
    assert(kbResponse.ok, `knowledge-bases returned ${kbResponse.status}`);
    const kb = (kbResponse.body.items || []).find((item) => item.name === knowledgeBaseName);
    assert(kb, `knowledge base ${knowledgeBaseName} was not found`);

    const graphResponse = await fetchJson(page, `/knowledge-bases/${kb.id}/knowledge-graph`);
    assert(graphResponse.ok, `graph endpoint returned ${graphResponse.status}`);
    const graph = graphResponse.body;
    assert(graph.status === 'ready', `graph was not ready: ${JSON.stringify(graph)}`);
    assert((graph.stats?.entity_count || 0) >= 2, `expected graph entities: ${JSON.stringify(graph.stats)}`);
    assert((graph.stats?.relation_count || 0) >= 1, `expected graph relations: ${JSON.stringify(graph.stats)}`);
    assert((graph.stats?.claim_count || 0) >= 1, `expected graph claims: ${JSON.stringify(graph.stats)}`);

    const relation = (graph.relations || [])[0];
    assert(relation?.id, 'graph smoke requires at least one relation with an id');
    const feedbackResponse = await fetchJson(
      page,
      `/knowledge-bases/${kb.id}/knowledge-graph/relations/${relation.id}/feedback`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ verdict: 'incorrect', note: 'demo smoke suppression check' }),
      },
    );
    assert(feedbackResponse.ok, `feedback endpoint returned ${feedbackResponse.status}`);
    const feedback = feedbackResponse.body;
    assert(feedback.feedback_summary?.incorrect >= 1, `feedback was not recorded: ${JSON.stringify(feedback)}`);

    const preferenceResponse = await fetchJson(page, `/knowledge-bases/${kb.id}/retrieval-preferences`);
    assert(preferenceResponse.ok, `preference endpoint returned ${preferenceResponse.status}`);
    const preference = preferenceResponse.body;
    assert(preference.preferences?.mode === 'hybrid_graph', `expected hybrid_graph preference: ${JSON.stringify(preference)}`);

    const graphQuery = `${relation.subject} ${relation.object}`;
    const retrievalResponse = await fetchJson(
      page,
      '/retrieval/search',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          knowledge_base: kb.name,
          query: graphQuery,
          top_k: 5,
          provider: 'deterministic-local',
          model: null,
          mode: preference.preferences.mode,
          graph_weight: preference.preferences.graph_weight,
          graph_depth: preference.preferences.graph_depth,
        }),
      },
    );
    assert(retrievalResponse.ok, `retrieval endpoint returned ${retrievalResponse.status}`);
    const retrieval = retrievalResponse.body;
    assert(retrieval.total_results >= 1, `expected retrieval hits: ${JSON.stringify(retrieval)}`);
    const graphContext = retrieval.graph_context || {};
    assert((graphContext.matched_entities || []).length >= 1, `expected matched graph entities: ${JSON.stringify(graphContext)}`);
    assert((graphContext.diagnostics?.suppressed_relation_count || 0) >= 1, `expected suppressed relation after feedback: ${JSON.stringify(graphContext)}`);

    await page.goto(`${baseURL}/retrieval-lab`, { waitUntil: 'domcontentloaded', timeout });
    await waitForText(page, 'main', /Retrieval Lab/);
    await waitForText(page, 'main', /Mode comparison/);
    await waitForText(page, 'main', /Graph Context/);
    await waitForText(page, 'main', /hybrid_graph/);
    await page.getByRole('button', { name: 'Compare modes' }).click();
    await waitForText(page, 'main', /Compared dense, graph, hybrid_graph, and graph_rerank modes/);
    const retrievalLabTitle = await textContent(page, 'h1');

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
        knowledge_map_title: knowledgeMapTitle,
        retrieval_lab_title: retrievalLabTitle,
        retrieval_lab_url: `${baseURL}/retrieval-lab`,
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
