export const STEPS = [
  { key: 'uploading', label: 'Uploading' },
  { key: 'extracting', label: 'Extracting' },
  { key: 'chunking', label: 'Chunking' },
  { key: 'embedding', label: 'Embedding' },
  { key: 'indexing', label: 'Indexing' },
  { key: 'ready', label: 'Ready' },
];

export function stepIndex(stage) {
  const i = STEPS.findIndex((s) => s.key === stage);
  return i === -1 ? 0 : i;
}
