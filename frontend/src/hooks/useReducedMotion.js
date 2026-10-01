import { useSyncExternalStore } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

function subscribe(callback) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {};
  const mql = window.matchMedia(QUERY);
  mql.addEventListener('change', callback);
  return () => mql.removeEventListener('change', callback);
}

const getSnapshot = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(QUERY).matches : false);

export function useReducedMotion() {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
