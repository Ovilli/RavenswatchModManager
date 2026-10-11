import { describe, expect, it } from 'vitest';
import { parseModManifest } from './manifest-toml';

describe('parseModManifest', () => {
  it('reads the [mod] table of a real-shaped manifest', () => {
    const m = parseModManifest(`# a comment
[mod]
id          = "second-wind"
name        = "Second Wind"
version     = "1.2.0"
author      = "RSMM"
description = "Go down once per run and you get back up swinging."
enabled     = false
load_order  = 50
# trailing comment between keys
license     = "MIT"
tags = ["survival", "events", 'quality-of-life']

[config.seed]
value = "ignored"
`);
    expect(m).toEqual({
      id: 'second-wind',
      name: 'Second Wind',
      version: '1.2.0',
      author: 'RSMM',
      description: 'Go down once per run and you get back up swinging.',
      license: 'MIT',
      tags: ['survival', 'events', 'quality-of-life'],
    });
  });

  it('handles multi-line arrays, multi-line strings and escapes', () => {
    const m = parseModManifest(`[mod]
id = "x"
tags = [
  "a",   # first
  "b, with comma",
]
description = """
Line one.
Line "two".
"""
name = "Quote \\"q\\" \\u00e9"
`);
    expect(m.tags).toEqual(['a', 'b, with comma']);
    expect(m.description).toBe('Line one.\nLine "two".');
    expect(m.name).toBe('Quote "q" é');
  });

  it('ignores keys outside [mod], even ones that look like mod keys', () => {
    const m = parseModManifest(`[overlay]
name = "not the mod"
[mod]
id = "real"
[content.values]
id = "also not"
`);
    expect(m).toEqual({ id: 'real' });
  });

  it('does not let [[content]] / [[patch]] blocks overwrite the mod’s own keys', () => {
    const m = parseModManifest(`[mod]
id = "real"
name = "Real Name"
description = "the mod's description"

[[content]]
kind = "talent"
id = "no_crash"
name = "Minimap_Marker"
description = "a content block"

[[patch]]
id = "also-not-the-mod"
`);
    expect(m).toEqual({ id: 'real', name: 'Real Name', description: "the mod's description" });
  });

  it('keeps a "[mod]" lookalike inside a multi-line string from switching tables', () => {
    const m = parseModManifest(`[overlay]
note = """
[mod]
id = "trap"
"""
[mod]
id = "real"
`);
    expect(m.id).toBe('real');
  });

  it('maps repo/homepage aliases, drops blanks and never throws on junk', () => {
    expect(
      parseModManifest(
        '[mod]\nrepository = "https://g/x"\nhomepage_url = "https://h"\nname = "  "',
      ),
    ).toEqual({
      repoUrl: 'https://g/x',
      homepageUrl: 'https://h',
    });
    expect(parseModManifest('')).toEqual({});
    expect(parseModManifest('\u0000\u0001 not toml [[[ = = "')).toEqual({});
    // A malformed value is dropped, not guessed at.
    expect(parseModManifest('[mod]\ntags = ["unterminated"')).toEqual({});
  });
});
