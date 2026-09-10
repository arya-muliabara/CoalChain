export async function refresh(base, secret, fetcher = fetch) {
  const response = await fetcher(new URL('/api/internal/refresh-alerts', base), {
    method: 'POST', headers: { Authorization: 'Bearer ' + secret }, signal: AbortSignal.timeout(10000)
  });
  if (!response.ok) throw new Error('API returned ' + response.status);
  return response.json();
}

