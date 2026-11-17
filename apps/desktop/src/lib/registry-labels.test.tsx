import { RegistryListingGallery, RegistryModCard, getRegistryMedia } from '@rsmm/ui';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { type Locale, type Vars, localeTag, translate } from './i18n';
import { registryCardLabels, registryGalleryLabels, registryMediaLabels } from './registry-labels';

function translator(locale: Locale) {
  return Object.assign((message: string, vars?: Vars) => translate(locale, message, vars), {
    locale,
    tag: localeTag(locale),
    n: (count: number, one: string, other: string, vars?: Vars) =>
      translate(locale, count === 1 ? one : other, { n: count, ...vars }),
  });
}

const mod = {
  slug: 'test-mod',
  name: '测试模组',
  author: '作者甲',
  imageUrl: '/cover.png',
  downloads: 1234,
  rating: 4.5,
  ratingCount: 12,
  featured: true,
  role: 'coauthor' as const,
};

describe('desktop shared registry translations', () => {
  it.each(['grid', 'list'] as const)('renders a translated %s card and accessible name', (view) => {
    const t = translator('zh-CN');
    const html = renderToStaticMarkup(
      <RegistryModCard mod={mod} view={view} locale={t.tag} labels={registryCardLabels(t, mod)} />,
    );
    expect(html).toContain('aria-label="测试模组，作者 作者甲"');
    expect(html).toContain('精选');
    if (view === 'grid') {
      expect(html).toContain('共同作者');
      expect(html).toContain('aria-label="评分 4.5，满分 5 星"');
      expect(html).toContain('alt="测试模组 预览"');
      expect(html).toContain('作者 作者甲');
    } else {
      expect(html).toContain('1,234 次下载');
    }
    expect(html).not.toMatch(/by 作者甲|out of 5 stars|Featured|Co-author|1,234 dl/);
  });

  it('translates generated media descriptions while preserving author captions and deduplication', () => {
    const media = getRegistryMedia(
      {
        ...mod,
        screenshots: [{ url: '/cover.png', caption: '作者说明' }, { url: '/second.png' }],
        videos: ['https://example.com/video'],
      },
      registryMediaLabels(translator('zh-CN')),
    );
    expect(media.map((item) => item.label)).toEqual([
      '作者说明',
      '测试模组 截图 2',
      '测试模组 视频 1',
    ]);
    const html = renderToStaticMarkup(
      <RegistryListingGallery
        media={media}
        name={mod.name}
        labels={registryGalleryLabels(translator('zh-CN'), mod.name)}
      />,
    );
    expect(html).toContain('aria-label="测试模组 图片和视频"');
    expect(html).toContain('aria-label="查看 测试模组 截图 2"');
    expect(html).toContain('显示全部媒体（3）');
    expect(html).not.toContain('Show all media');
  });

  it('translates the mature-content gate and empty gallery', () => {
    const labels = registryGalleryLabels(translator('zh-CN'), mod.name);
    const media = getRegistryMedia(mod, registryMediaLabels(translator('zh-CN')));
    const gated = renderToStaticMarkup(
      <RegistryListingGallery media={media} name={mod.name} nsfw labels={labels} />,
    );
    expect(gated).toContain('此模组包含成人内容。');
    expect(gated).toContain('显示媒体');
    expect(gated).not.toContain('src="/cover.png"');
    const empty = renderToStaticMarkup(
      <RegistryListingGallery media={[]} name={mod.name} labels={labels} />,
    );
    expect(empty).toContain('尚未添加图片。');
  });

  it('retains English website defaults when labels are omitted', () => {
    const media = getRegistryMedia(mod);
    expect(media[0]?.label).toBe('测试模组 cover');
    const gallery = renderToStaticMarkup(<RegistryListingGallery media={media} name={mod.name} />);
    expect(gallery).toContain('View full image');
    const card = renderToStaticMarkup(<RegistryModCard mod={mod} />);
    expect(card).toContain('by 作者甲');
    expect(card).toContain('4.5 out of 5 stars');
  });

  it('recomputes labels when the desktop language changes', () => {
    expect(registryGalleryLabels(translator('en'), mod.name).showMedia).toBe('Show media');
    expect(registryGalleryLabels(translator('zh-CN'), mod.name).showMedia).toBe('显示媒体');
  });
});
