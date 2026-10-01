import { useId, useState } from 'react';
import Icon from './Icon';

export default function Field({ label, type = 'text', hint, ...props }) {
  const id = useId();
  const [show, setShow] = useState(false);
  const isPassword = type === 'password';
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="field-control">
        <input id={id} type={isPassword && show ? 'text' : type} aria-describedby={hint ? `${id}-hint` : undefined} {...props} />
        {isPassword && (
          <button type="button" className="field-toggle" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}>
            <Icon name={show ? 'eyeOff' : 'eye'} size={17} />
          </button>
        )}
      </div>
      {hint && (
        <p id={`${id}-hint`} className="field-hint">
          {hint}
        </p>
      )}
    </div>
  );
}
