/**
 * CSS-only 3D primitives. No WebGL: transforms + gradients run on the compositor,
 * cost ~0 KB of library code, and degrade to a static scene with reduced motion.
 *
 * Every component is decorative (aria-hidden) and positioned by data, so scenes
 * are arrays of plain objects rendered by <Scene />.
 */
import { useEffect, useRef } from 'react';
import { useReducedMotion } from '../../hooks/useReducedMotion';

const cx = (...c) => c.filter(Boolean).join(' ');

/** Parallax plane: moves with the pointer proportionally to `depth` (0 = fixed, 1 = near). */
export function DepthLayer({ depth = 0.5, className, style, children }) {
  return (
    <div className={cx('depth-layer', className)} style={{ '--depth': depth, ...style }} aria-hidden="true">
      {children}
    </div>
  );
}

/** A sheet of paper with a folded corner, type label and text lines. */
export function FloatingDocument({ label = 'PDF', title, tone = 'sky', size = 1 }) {
  return (
    <div className={cx('fdoc', `tone-${tone}`)} style={{ '--s': size }}>
      <div className="fdoc-sheet fdoc-back" />
      <div className="fdoc-sheet">
        <span className="fdoc-fold" />
        <span className="fdoc-label">{label}</span>
        {title && <span className="fdoc-title">{title}</span>}
        <span className="fdoc-line w90" />
        <span className="fdoc-line w70" />
        <span className="fdoc-line w80" />
        <span className="fdoc-line w50" />
      </div>
    </div>
  );
}

/** Glossy sphere with an optional glyph (used for "Search", "Chat", "Citation" bubbles). */
export function FloatingOrb({ label, tone = 'sky', size = 1 }) {
  return (
    <div className={cx('forb', `tone-${tone}`)} style={{ '--s': size }}>
      <span className="forb-shine" />
      {label && <span className="forb-label">{label}</span>}
    </div>
  );
}

/** The AI core: orb with orbiting rings. */
export function FloatingAIOrb({ size = 1, label = 'AI' }) {
  return (
    <div className="faio" style={{ '--s': size }}>
      <span className="faio-ring r1" />
      <span className="faio-ring r2" />
      <span className="faio-core">
        <span className="forb-shine" />
        <span className="faio-label">{label}</span>
      </span>
    </div>
  );
}

/** An embedding vector drawn as a tilted strip of value bars. */
export function FloatingVector({ size = 1, bars = 12, seed = 3, label }) {
  const values = Array.from({ length: bars }, (_, i) => 0.25 + (((i * 7 + seed * 13) % 11) / 11) * 0.75);
  return (
    <div className="fvec" style={{ '--s': size }}>
      <div className="fvec-plate">
        {values.map((v, i) => (
          <span key={i} className="fvec-bar" style={{ '--v': v }} />
        ))}
      </div>
      {label && <span className="fvec-label">{label}</span>}
    </div>
  );
}

/** A surface with real depth: layered shadow, optional pointer tilt (off for reduced motion). */
export function ThreeDCard({ as: Tag = 'div', tilt = 0, className, children, ...rest }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();
  const enabled = tilt > 0 && !reduced;

  const onMove = (e) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty('--tx', `${(-y * tilt).toFixed(2)}deg`);
    el.style.setProperty('--ty', `${(x * tilt).toFixed(2)}deg`);
  };
  const onLeave = () => {
    ref.current?.style.setProperty('--tx', '0deg');
    ref.current?.style.setProperty('--ty', '0deg');
  };

  return (
    <Tag
      ref={ref}
      className={cx('card3d', className)}
      onPointerMove={enabled ? onMove : undefined}
      onPointerLeave={enabled ? onLeave : undefined}
      {...rest}
    >
      {children}
    </Tag>
  );
}

const RENDERERS = {
  document: FloatingDocument,
  orb: FloatingOrb,
  ai: FloatingAIOrb,
  vector: FloatingVector,
};

/**
 * Data-driven decorative scene. Each item: {type, x, y, depth, rotate, delay, props, hideBelow}
 * x/y are percentages of the scene box; hideBelow ('md' | 'lg') drops items on smaller screens.
 */
export function Scene({ items, className }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || reduced) return undefined;
    let frame = 0;
    const onMove = (e) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        el.style.setProperty('--px', (e.clientX / window.innerWidth - 0.5).toFixed(3));
        el.style.setProperty('--py', (e.clientY / window.innerHeight - 0.5).toFixed(3));
      });
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', onMove);
    };
  }, [reduced]);

  return (
    <div ref={ref} className={cx('scene', className)} aria-hidden="true">
      {items.map((item) => {
        const Comp = RENDERERS[item.type];
        return (
          <DepthLayer
            key={item.id}
            depth={item.depth}
            className={cx('scene-item', item.hideBelow && `hide-below-${item.hideBelow}`)}
            style={{ left: `${item.x}%`, top: `${item.y}%` }}
          >
            <div className="float" style={{ '--r': `${item.rotate || 0}deg`, '--delay': `${item.delay || 0}s`, '--dur': `${item.duration || 9}s` }}>
              <Comp {...item.props} />
            </div>
          </DepthLayer>
        );
      })}
    </div>
  );
}
