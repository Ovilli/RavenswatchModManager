'use client';

import type { MDEditorProps } from '@uiw/react-md-editor';
import dynamic from 'next/dynamic';
import type { ComponentProps } from 'react';
import { rehypeSafeHtml } from '../../lib/md-preview';

/**
 * The only way this site renders `@uiw/react-md-editor`. Both its `Markdown`
 * preview and the editor's live preview pane run `rehype-raw`, so each gets
 * `rehypeSafeHtml` appended — see lib/md-preview.ts for why that matters. Do not
 * import the library directly in a page: a user-supplied body shown without
 * this plugin is stored XSS.
 */

type PreviewProps = ComponentProps<typeof import('@uiw/react-md-editor').default.Markdown>;

export const MDPreview = dynamic(
  () =>
    import('@uiw/react-md-editor').then((m) => {
      const Markdown = m.default.Markdown;
      return function SafeMarkdown(props: PreviewProps) {
        return <Markdown {...props} rehypePlugins={[rehypeSafeHtml]} />;
      };
    }),
  { ssr: false },
);

export const MDEditor = dynamic(
  () =>
    import('@uiw/react-md-editor').then((m) => {
      const Editor = m.default;
      return function SafeEditor(props: MDEditorProps) {
        return (
          <Editor
            {...props}
            previewOptions={{ ...props.previewOptions, rehypePlugins: [rehypeSafeHtml] }}
          />
        );
      };
    }),
  { ssr: false },
);
