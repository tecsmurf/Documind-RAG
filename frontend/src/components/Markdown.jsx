/**
 * Safe Markdown for untrusted model output.
 * - raw HTML is dropped (skipHtml), never parsed
 * - images are not rendered (a prompt-injected image URL could exfiltrate data)
 * - links only for http(s)/mailto; anything else (javascript:, data:, vbscript:) becomes plain text
 * - inline [n] markers become buttons for citations that really exist
 */
import { Children, cloneElement, isValidElement, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeUrl } from '../lib/markdown';


function withCitations(children, citations, onCite) {
  if (!citations?.length) return children;
  const valid = new Set(citations.map((c) => String(c.index)));
  return Children.map(children, (child) => {
    if (typeof child === 'string') {
      const parts = child.split(/(\[\d{1,2}\])/g);
      if (parts.length === 1) return child;
      return parts.map((part, i) => {
        const m = part.match(/^\[(\d{1,2})\]$/);
        if (m && valid.has(m[1])) {
          const cite = citations.find((c) => String(c.index) === m[1]);
          return (
            <button
              key={i}
              type="button"
              className="cite-ref"
              onClick={() => onCite?.(cite)}
              aria-label={`Source ${m[1]}: ${cite.filename}${cite.page_number ? `, page ${cite.page_number}` : ''}`}
            >
              {m[1]}
            </button>
          );
        }
        return part;
      });
    }
    if (isValidElement(child) && child.props?.children && typeof child.type === 'string' && child.type !== 'code') {
      return cloneElement(child, undefined, withCitations(child.props.children, citations, onCite));
    }
    return child;
  });
}

function buildComponents(citations, onCite) {
  const wrap = (Tag) =>
    function Wrapped({ node: _node, children, ...props }) {
      return <Tag {...props}>{withCitations(children, citations, onCite)}</Tag>;
    };
  return {
    p: wrap('p'),
    li: wrap('li'),
    td: wrap('td'),
    strong: wrap('strong'),
    em: wrap('em'),
    img: ({ alt }) => (alt ? <span className="md-img-alt">[image: {alt}]</span> : null),
    a: ({ href, children }) => {
      const url = safeUrl(href);
      if (!url) return <span>{children}</span>;
      return (
        <a href={url} target="_blank" rel="noopener noreferrer nofollow">
          {children}
        </a>
      );
    },
  };
}

const REMARK = [remarkGfm];

export default function Markdown({ text, citations, onCite }) {
  // Stable component identities so streaming tokens don't remount the whole answer.
  const components = useMemo(() => buildComponents(citations, onCite), [citations, onCite]);
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={REMARK} skipHtml urlTransform={safeUrl} components={components}>
        {text || ''}
      </ReactMarkdown>
    </div>
  );
}
