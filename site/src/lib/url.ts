/**
 * Prefix an internal path with the configured base (`/tinybrains-blog`).
 * - `url()` → `/tinybrains-blog/`
 * - `url('archive/')` / `url('/archive/')` → `/tinybrains-blog/archive/`
 * - absolute URLs (`https://…`, `mailto:`, `#…`) are returned untouched
 * - paths already starting with the base are returned untouched
 */
export function url(path = ''): string {
  const base = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '');
  if (/^([a-z][a-z0-9+.-]*:|#|\/\/)/i.test(path)) return path;
  if (base && (path === base || path.startsWith(base + '/'))) return path;
  const clean = path.replace(/^\/+/, '');
  return `${base}/${clean}`;
}

/** Absolute URL on the public site, for share links / canonical tags. */
export function absUrl(path = '', site: URL | string | undefined): string {
  const origin = site ? new URL(String(site)).origin : '';
  return origin + url(path);
}
