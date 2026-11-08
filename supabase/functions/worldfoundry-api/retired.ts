// The v0.2 provider-token prototype is retired. Customer requests must enter
// through the WorldFoundry gateway and the company customer API.
Deno.serve(() => Response.json({ error: 'Not found' }, { status: 404 }))
