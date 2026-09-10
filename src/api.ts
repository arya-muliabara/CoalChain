export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('X-MCMS-Request', '1');
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch('/api' + path, { ...options, headers, credentials: 'same-origin' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((e: any) => e.msg).join('; ') : 'Permintaan gagal (' + response.status + ')';
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('session-expired'));
    throw new Error(message);
  }
  return response.json();
}
export const send = (path: string, body: unknown, method = 'POST') => api(path, {method, body: JSON.stringify(body)});
export const number = (value: number | null | undefined, digits = 0) => value == null ? '—' : new Intl.NumberFormat('id-ID', {maximumFractionDigits: digits}).format(value);
export const rupiah = (value: number) => 'Rp ' + number(value);
export const compact = (value: number) => new Intl.NumberFormat('id-ID', {notation:'compact', maximumFractionDigits:1}).format(value);
export interface Field {key: string; label: string; type: string; required: boolean; options: string[]; ref: string | null}
export interface Module {label: string; group: string; fields: Field[]; columns: string[]; writers: string[]; workflow: string[]; can_write: boolean}
export interface Row {id: string; kind: string; status: string; version: number; [key: string]: any}
export interface Lookup {id: string; kind: string; name: string; status: string; site_id?: string; contractor_id?: string; activity?: string; date?: string}
export interface User {id: string; name: string; email: string; role: string; site_id?: string; contractor_id?: string}

