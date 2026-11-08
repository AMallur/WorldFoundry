// Customer-facing WorldFoundry gateway. Provider address and gateway token
// exist only in Vercel server-side environment variables.
export default async function handler(req, res) {
  const upstream = process.env.WF_INTERNAL_API_URL;
  const gatewayToken = process.env.WF_GATEWAY_TOKEN;
  if (!upstream || !gatewayToken) {
    res.status(503).json({ error: 'WorldFoundry service unavailable' });
    return;
  }

  const route = String(req.query.route ?? '').split('/').filter(Boolean);
  if (!route.length || route.some(part => !/^[a-zA-Z0-9_-]+$/.test(part))) {
    res.status(404).json({ error: 'Not found' });
    return;
  }
  if (!['GET', 'POST', 'PATCH', 'DELETE'].includes(req.method)) {
    res.setHeader('Allow', 'GET, POST, PATCH, DELETE');
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }

  const url = new URL(`${upstream.replace(/\/$/, '')}/v1/${route.join('/')}`);
  const original = new URL(req.url, 'https://worldfoundry.invalid');
  for (const [name, value] of original.searchParams) {
    if (name !== 'route') url.searchParams.append(name, value);
  }
  const headers = { 'x-wf-gateway-token': gatewayToken };
  if (req.headers.authorization) headers.authorization = req.headers.authorization;
  if (req.headers.cookie) headers.cookie = req.headers.cookie;
  if (req.headers['x-wf-csrf']) headers['x-wf-csrf'] = req.headers['x-wf-csrf'];
  if (req.headers['content-type']) headers['content-type'] = req.headers['content-type'];

  try {
    const response = await fetch(url, {
      method: req.method,
      headers,
      body: ['POST', 'PATCH'].includes(req.method) ? JSON.stringify(req.body ?? {}) : undefined,
      redirect: 'manual',
      signal: AbortSignal.timeout(30000),
    });
    res.status(response.status);
    res.setHeader('Cache-Control', 'no-store');
    const contentType = response.headers.get('content-type');
    if (contentType) res.setHeader('Content-Type', contentType);
    // Upstream infrastructure may set provider-domain cookies. Only forward
    // WorldFoundry's own session and CSRF cookies to customers.
    const cookies = response.headers.getSetCookie()
      .filter(value => /^(wf_session|wf_csrf)=/.test(value));
    if (cookies.length) res.setHeader('Set-Cookie', cookies);
    res.send(Buffer.from(await response.arrayBuffer()));
  } catch {
    res.status(502).json({ error: 'WorldFoundry service unavailable' });
  }
}
