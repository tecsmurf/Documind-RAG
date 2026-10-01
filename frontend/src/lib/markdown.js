const SAFE_URL = /^(https?:|mailto:)/i;

/** Only http(s) and mailto links survive; javascript:, data:, vbscript:, relative tricks become ''. */
export function safeUrl(url) {
  if (typeof url !== 'string') return '';
  const trimmed = url.trim();
  return SAFE_URL.test(trimmed) ? trimmed : '';
}

export function citationLabel(c) {
  return `${c.filename || 'Document'}${c.page_number ? ` · p. ${c.page_number}` : ''}`;
}
