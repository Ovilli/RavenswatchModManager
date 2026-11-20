import { RegistryListingCard } from '@rsmm/ui';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

const listing = {
  slug: 'shared-row',
  name: 'Shared row',
  author: 'Mod author',
  summary: 'A sample mod.',
  imageUrl: '/thumbnail.png',
  downloads: 1200,
  rating: 4.5,
};

describe('shared listing rows', () => {
  it('keeps registry statistics and navigation when no Library slots are supplied', () => {
    const html = renderToStaticMarkup(
      <RegistryListingCard listing={listing} view="list" onOpen={() => {}} />,
    );
    expect(html).toContain('role="link"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('1,200 dl');
    expect(html).toContain('★ 4.5');
  });

  it('lets Library replace statistics while sharing identity, artwork and scope badges', () => {
    const html = renderToStaticMarkup(
      <RegistryListingCard
        listing={listing}
        view="list"
        privateOnly
        listLeading={<button type="button">Enable</button>}
        listMetadata={<span>v1.2.3</span>}
        listBadges={<span>Missing dependency</span>}
        actions={<button type="button">Uninstall</button>}
      />,
    );
    expect(html).toContain('src="/thumbnail.png"');
    expect(html).toContain('Mod author — A sample mod.');
    expect(html).toContain('Private games only');
    expect(html).toContain('Missing dependency');
    expect(html).toContain('v1.2.3');
    expect(html).toContain('>Enable</button>');
    expect(html).toContain('>Uninstall</button>');
    expect(html).not.toMatch(/mod-card-list-rating|mod-card-list-downloads|role="link"|tabindex=/);
  });

  it('keeps a cover and author fallback for local mods without registry metadata', () => {
    const html = renderToStaticMarkup(
      <RegistryListingCard
        listing={{ slug: 'local-only', name: 'Local mod' }}
        view="list"
        listMetadata={<span>v1.0.0</span>}
      />,
    );
    expect(html).toContain('mod-card-list-art');
    expect(html).toContain('unknown');
    expect(html).not.toMatch(/<img|Private games only|role="link"/);
  });
});
