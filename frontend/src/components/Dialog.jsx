import { useEffect, useRef } from 'react';
import Icon from './Icon';

/**
 * Accessible modal built on <dialog>: native focus trapping, Esc to close,
 * focus returns to the opener, background is inert.
 */
export default function Dialog({ open, onClose, title, children, footer, className = '' }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal?.();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`dialog ${className}`}
      aria-labelledby="dialog-title"
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // click on backdrop
      }}
    >
      {open && (
        <div className="dialog-body">
          <header className="dialog-head">
            <h2 id="dialog-title">{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
              <Icon name="close" />
            </button>
          </header>
          <div className="dialog-content">{children}</div>
          {footer && <footer className="dialog-foot">{footer}</footer>}
        </div>
      )}
    </dialog>
  );
}
