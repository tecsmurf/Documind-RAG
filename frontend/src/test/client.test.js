import { describe, expect, it } from 'vitest';
import { errorMessage } from '../api/client';
import { precheckFile } from '../lib/format';
import { stepIndex } from '../lib/steps';

describe('errorMessage', () => {
  it('shows safe backend details for 4xx', () => {
    expect(errorMessage({ response: { status: 401, data: { detail: 'Invalid email or password.' } } })).toBe('Invalid email or password.');
    expect(errorMessage({ response: { status: 429, data: { detail: 'Too many requests. Please wait 2 seconds and try again.' } } })).toMatch(/wait 2 seconds/);
  });
  it('never shows 5xx bodies', () => {
    expect(errorMessage({ response: { status: 500, data: { detail: 'sqlalchemy.exc.OperationalError postgres://u:p@h' } } })).toBe(
      'Something went wrong. Please try again.',
    );
  });
  it('explains network failures', () => {
    expect(errorMessage({ code: 'ERR_NETWORK' })).toMatch(/reach the server/);
  });
  it('summarises validation errors by field', () => {
    expect(errorMessage({ response: { status: 422, data: { detail: 'Invalid request.', errors: [{ field: 'email', message: 'value is not a valid email address' }] } } })).toBe(
      'Email: value is not a valid email address',
    );
  });
});

describe('upload precheck (UX only; server re-validates)', () => {
  const file = (name, size) => ({ name, size });
  it('accepts pdf/txt/md and rejects others, empty and oversized', () => {
    expect(precheckFile(file('a.PDF', 10))).toBe('');
    expect(precheckFile(file('a.md', 10))).toBe('');
    expect(precheckFile(file('a.exe', 10))).toMatch(/Only PDF/);
    expect(precheckFile(file('a.txt', 0))).toMatch(/empty/);
    expect(precheckFile(file('a.txt', 11 * 1024 * 1024))).toMatch(/larger than/);
  });
});

describe('processing steps', () => {
  it('maps backend stages in order', () => {
    expect(['uploading', 'extracting', 'chunking', 'embedding', 'indexing', 'ready'].map(stepIndex)).toEqual([0, 1, 2, 3, 4, 5]);
  });
});
