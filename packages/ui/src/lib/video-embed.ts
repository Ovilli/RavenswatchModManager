/** Convert supported video watch URLs into privacy-conscious embed URLs. */
export function toEmbedUrl(input: string): string | null {
  let url: URL;
  try {
    url = new URL(input);
  } catch {
    return null;
  }
  const host = url.hostname.replace(/^www\./, '').toLowerCase();
  if (host === 'youtube.com' || host === 'm.youtube.com') {
    if (url.pathname === '/watch') {
      const id = url.searchParams.get('v');
      if (id) return `https://www.youtube.com/embed/${encodeURIComponent(id)}`;
    }
    if (url.pathname.startsWith('/embed/') || url.pathname.startsWith('/shorts/')) {
      const id = url.pathname.split('/')[2];
      if (id) return `https://www.youtube.com/embed/${encodeURIComponent(id)}`;
    }
  }
  if (host === 'youtu.be') {
    const id = url.pathname.replace(/^\//, '').split('/')[0];
    if (id) return `https://www.youtube.com/embed/${encodeURIComponent(id)}`;
  }
  if (host === 'vimeo.com') {
    const id = url.pathname.split('/').filter(Boolean)[0];
    if (id && /^\d+$/.test(id)) return `https://player.vimeo.com/video/${id}`;
  }
  if (host === 'player.vimeo.com' && url.pathname.startsWith('/video/')) {
    const id = url.pathname.split('/')[2];
    if (id && /^\d+$/.test(id)) return `https://player.vimeo.com/video/${id}`;
  }
  return null;
}
