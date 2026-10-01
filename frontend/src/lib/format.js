export function formatSize(bytes) {
  if (!Number.isFinite(bytes)) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' });
}

export const ALLOWED_TYPES = ['pdf', 'txt', 'md'];
export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB) || 10;

/** Client-side pre-check for fast feedback only; the server re-validates everything. */
export function precheckFile(file) {
  const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
  if (!ALLOWED_TYPES.includes(ext)) return 'Only PDF, TXT and MD files are supported.';
  if (file.size === 0) return 'This file is empty.';
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `This file is larger than ${MAX_UPLOAD_MB} MB.`;
  return '';
}

export const fileKind = (doc) => (doc.file_type || 'file').toUpperCase();
