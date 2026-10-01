import Logo from './Logo';
import { Scene, ThreeDCard } from './three-d';

/** Floating objects around the auth card. Fewer on tablets, almost none on phones. */
const AUTH_SCENE = [
  { id: 'doc-top', type: 'document', x: 46, y: 4, depth: 0.5, rotate: -8, delay: 0, props: { label: 'DOC', size: 0.85 }, hideBelow: 'md' },
  { id: 'pdf', type: 'document', x: 12, y: 22, depth: 0.9, rotate: -14, delay: 1.2, props: { label: 'PDF', title: 'Research', size: 1 } },
  { id: 'ai', type: 'ai', x: 78, y: 18, depth: 0.8, delay: 0.6, props: { size: 1.05 } },
  { id: 'vector', type: 'vector', x: 8, y: 66, depth: 0.6, rotate: 10, delay: 2, props: { label: 'Vector', size: 0.95 }, hideBelow: 'md' },
  { id: 'search', type: 'orb', x: 82, y: 64, depth: 0.7, delay: 1.6, props: { label: 'Search', tone: 'cyan', size: 0.9 }, hideBelow: 'md' },
  { id: 'cite', type: 'orb', x: 28, y: 84, depth: 0.35, delay: 2.6, props: { label: '[1]', tone: 'white', size: 0.6 }, hideBelow: 'lg' },
  { id: 'md', type: 'document', x: 68, y: 82, depth: 0.45, rotate: 12, delay: 3.1, props: { label: 'MD', size: 0.7, tone: 'cyan' }, hideBelow: 'lg' },
  { id: 'chat', type: 'orb', x: 90, y: 40, depth: 0.3, delay: 0.9, props: { label: 'Chat', tone: 'white', size: 0.55 }, hideBelow: 'lg' },
];

export default function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="auth-page">
      <div className="sky" aria-hidden="true">
        <div className="sky-glow g1" />
        <div className="sky-glow g2" />
        <div className="floor-grid" />
      </div>
      <Scene items={AUTH_SCENE} className="auth-scene" />
      <main className="auth-main">
        <ThreeDCard className="auth-card" tilt={0}>
          <div className="auth-head">
            <Logo size="lg" />
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          {children}
          <div className="auth-foot">{footer}</div>
        </ThreeDCard>
        <p className="auth-tagline">Ask your documents anything. Every answer cites its source.</p>
      </main>
    </div>
  );
}
