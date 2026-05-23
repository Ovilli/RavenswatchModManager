/**
 * Convert a YouTube or Vimeo watch URL into an embeddable iframe URL.
 *
 * Returns null for unsupported hosts so callers can render a fallback
 * link instead of pulling in a generic <iframe> that browsers will
 * block on CSP / frame-ancestors anyway.
 */
export function toEmbedUrl(input: string): string | null {
  let u: URL;
  try {
    u = new URL(input);
  } catch {
    return null;
  }
  const host = u.hostname.replace(/^www\./, '').toLowerCase();

  // YouTube — accepts the canonical watch URL, the shortlink form, and
  // both /embed/<id> and /shorts/<id>. Strips extra query params so the
  // iframe loads clean (no autoplay flags, no playlist context).
  if (host === 'youtube.com' || host === 'm.youtube.com') {
    if (u.pathname === '/watch') {
      const id = u.searchParams.get('v');
      if (id) return `https://www.youtube.com/embed/${encodeURIComponent(id)}`;
    }
    if (u.pathname.startsWith('/embed/') || u.pathname.startsWith('/shorts/')) {
      const id = u.pathname.split('/')[2];
      if (id) return `https://www.youtube.com/embed/${encodeURIComponent(id)}`;
    }
  }
  if (host === 'youtu.be') {
    const id = u.pathname.replace(/^\//, '').split('/')[0];
    if (id) return `https://www.youtube.com/embed/${encodeURIComponent(id)}`;
  }

  // Vimeo — accepts vimeo.com/<id> and player.vimeo.com/video/<id>.
  if (host === 'vimeo.com') {
    const id = u.pathname.split('/').filter(Boolean)[0];
    if (id && /^\d+$/.test(id)) return `https://player.vimeo.com/video/${id}`;
  }
  if (host === 'player.vimeo.com' && u.pathname.startsWith('/video/')) {
    const id = u.pathname.split('/')[2];
    if (id && /^\d+$/.test(id)) return `https://player.vimeo.com/video/${id}`;
  }

  return null;
}
