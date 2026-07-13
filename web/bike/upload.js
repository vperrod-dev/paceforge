// Upload clients for intervals.icu and Strava. Plain fetch + FormData,
// no retries — the caller decides what to do on failure.

// intervals.icu: Basic auth with username literally "API_KEY" and the
// user's key as password. Athlete id 0 = "the authenticated athlete".
export async function uploadIntervalsIcu(fitBytes, { apiKey, name }) {
  const form = new FormData();
  form.append('file', new Blob([fitBytes]), 'ride.fit');
  if (name) form.append('name', name);
  const res = await fetch('https://intervals.icu/api/v1/athlete/0/activities', {
    method: 'POST',
    headers: { Authorization: `Basic ${btoa(`API_KEY:${apiKey}`)}` },
    body: form,
  });
  if (!res.ok) throw new Error(`intervals.icu upload failed (${res.status}): ${await res.text()}`);
  return res.json();
}

// Strava upload API. Strava requires a registered OAuth app and periodic
// token refresh; the UI stores a manually-obtained access token for now.
// ponytail: manual token, OAuth flow when it matters
export async function uploadStrava(fitBytes, { accessToken, name }) {
  const form = new FormData();
  form.append('file', new Blob([fitBytes]), 'ride.fit');
  form.append('data_type', 'fit');
  if (name) form.append('name', name);
  form.append('trainer', '1');
  const res = await fetch('https://www.strava.com/api/v3/uploads', {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
    body: form,
  });
  if (!res.ok) throw new Error(`Strava upload failed (${res.status}): ${await res.text()}`);
  return res.json();
}
