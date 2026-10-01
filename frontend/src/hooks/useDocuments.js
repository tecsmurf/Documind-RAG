import { useCallback, useEffect, useRef, useState } from 'react';
import { docsAPI, errorMessage } from '../api/client';

const POLL_MS = 2000;

/**
 * Document library state, always mirroring the backend. While any document is
 * `processing`, the list is polled so stages and chunk counts are real values.
 */
export function useDocuments() {
  const [documents, setDocuments] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [uploads, setUploads] = useState([]); // in-flight HTTP uploads (before the server has a row)
  const timer = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const res = await docsAPI.list();
      setDocuments(res.data);
      setLoadError('');
      return res.data;
    } catch (err) {
      setLoadError(errorMessage(err, 'Could not load your documents.'));
      return null;
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(refresh);
  }, [refresh]);

  const processing = documents.some((d) => d.status === 'processing');
  useEffect(() => {
    if (!processing) return undefined;
    timer.current = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(timer.current);
  }, [processing, documents, refresh]);

  const upload = useCallback(
    async (file, { replaces } = {}) => {
      const key = `${file.name}-${file.size}-${Date.now()}`;
      setUploads((u) => [...u, { key, filename: file.name, progress: 0, error: '' }]);
      try {
        await docsAPI.upload(file, (e) => {
          const progress = e.total ? Math.round((e.loaded / e.total) * 100) : 0;
          setUploads((u) => u.map((x) => (x.key === key ? { ...x, progress } : x)));
        });
        setUploads((u) => u.filter((x) => x.key !== key));
        if (replaces) {
          try {
            await docsAPI.remove(replaces);
          } catch {
            /* the backend may already have replaced it */
          }
        }
        await refresh();
        return { ok: true };
      } catch (err) {
        const message = errorMessage(err, 'Something went wrong while uploading your document.');
        setUploads((u) => u.map((x) => (x.key === key ? { ...x, error: message } : x)));
        return { ok: false, message };
      }
    },
    [refresh],
  );

  const dismissUpload = useCallback((key) => setUploads((u) => u.filter((x) => x.key !== key)), []);

  const remove = useCallback(
    async (id) => {
      await docsAPI.remove(id);
      setDocuments((docs) => docs.filter((d) => d.id !== id));
      refresh();
    },
    [refresh],
  );

  return { documents, loaded, loadError, uploads, upload, dismissUpload, remove, refresh };
}
