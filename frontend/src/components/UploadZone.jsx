import { useRef, useState } from 'react';
import { precheckFile, MAX_UPLOAD_MB } from '../lib/format';
import Icon from './Icon';
import { FloatingDocument } from './three-d';

/**
 * 3D drop zone. Lifts and glows on drag-over; keyboard users get a real button.
 * `variant="hero"` is the large empty-state version, `"compact"` sits in the sidebar.
 */
export default function UploadZone({ onFiles, variant = 'hero', disabled = false, inputRef: externalRef }) {
  const [over, setOver] = useState(false);
  const [hint, setHint] = useState('');
  const localRef = useRef(null);
  const inputRef = externalRef || localRef;
  const depth = useRef(0);

  const handle = (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const problems = files.map((f) => [f, precheckFile(f)]);
    const bad = problems.find(([, p]) => p);
    setHint(bad ? `${bad[0].name}: ${bad[1]}` : '');
    const good = problems.filter(([, p]) => !p).map(([f]) => f);
    if (good.length) onFiles(good);
  };

  return (
    <div
      className={`dropzone dropzone-${variant} ${over ? 'is-over' : ''} ${disabled ? 'is-disabled' : ''}`}
      onDragEnter={(e) => {
        e.preventDefault();
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => {
        depth.current -= 1;
        if (depth.current <= 0) setOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        depth.current = 0;
        setOver(false);
        if (!disabled) handle(e.dataTransfer.files);
      }}
    >
      <div className="dropzone-surface">
        {variant === 'hero' && (
          <div className="dropzone-object" aria-hidden="true">
            <FloatingDocument label="PDF" size={0.9} />
            <span className="dropzone-arrow">
              <Icon name="upload" size={22} strokeWidth={2.2} />
            </span>
          </div>
        )}
        <div className="dropzone-copy">
          <p className="dropzone-title">{variant === 'hero' ? 'Drop a document here' : 'Add a document'}</p>
          <p className="dropzone-sub">PDF · TXT · MD, up to {MAX_UPLOAD_MB} MB</p>
        </div>
        <button type="button" className={variant === 'hero' ? 'btn btn-primary' : 'btn btn-soft btn-sm'} disabled={disabled}
          onClick={() => inputRef.current?.click()}>
          <Icon name="upload" size={16} /> {variant === 'hero' ? 'Choose file' : 'Upload'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
          multiple
          hidden
          onChange={(e) => {
            handle(e.target.files);
            e.target.value = '';
          }}
        />
      </div>
      {hint && (
        <p className="dropzone-hint" role="alert">
          {hint}
        </p>
      )}
    </div>
  );
}
