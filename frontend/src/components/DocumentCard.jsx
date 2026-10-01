import { formatDate, formatSize, fileKind } from '../lib/format';
import Icon from './Icon';
import ProcessingSteps from './ProcessingSteps';
import { ThreeDCard } from './three-d';

const STATUS_LABEL = { ready: 'Ready', processing: 'Processing', error: 'Error' };

export default function DocumentCard({ doc, onDelete, onRetry }) {
  const kind = fileKind(doc);
  return (
    <ThreeDCard as="li" className={`doc-card status-${doc.status}`} tilt={4}>
      <div className="doc-card-main">
        <span className={`file-tile kind-${doc.file_type}`} aria-hidden="true">
          <span className="file-tile-fold" />
          {kind}
        </span>
        <div className="doc-card-text">
          <p className="doc-name" title={doc.filename}>
            {doc.filename}
          </p>
          <p className="doc-meta">
            <span className={`pill pill-${doc.status}`}>
              <span className="pill-dot" aria-hidden="true" />
              {STATUS_LABEL[doc.status] || doc.status}
            </span>
            {doc.status === 'ready' && (
              <span>
                {doc.total_chunks} {doc.total_chunks === 1 ? 'chunk' : 'chunks'}
              </span>
            )}
            {doc.page_count ? <span>{doc.page_count} pp</span> : null}
            <span>{formatSize(doc.file_size)}</span>
            <time dateTime={doc.created_at}>{formatDate(doc.created_at)}</time>
          </p>
        </div>
        <div className="doc-actions">
          {doc.status === 'error' && (
            <button type="button" className="icon-btn" onClick={() => onRetry(doc)} aria-label={`Retry ${doc.filename}`} title="Retry">
              <Icon name="retry" size={16} />
            </button>
          )}
          <button type="button" className="icon-btn danger" onClick={() => onDelete(doc)} aria-label={`Delete ${doc.filename}`} title="Delete">
            <Icon name="trash" size={16} />
          </button>
        </div>
      </div>
      {doc.status === 'processing' && <ProcessingSteps stage={doc.processing_stage || 'uploading'} compact />}
      {doc.status === 'error' && (
        <div className="doc-error" role="status">
          <p>{doc.error_message || 'Document processing failed.'}</p>
          <button type="button" className="link-btn" onClick={() => onRetry(doc)}>
            <Icon name="retry" size={14} /> Retry upload
          </button>
        </div>
      )}
    </ThreeDCard>
  );
}

/** A browser-side upload that the server has not accepted yet. */
export function UploadingCard({ upload, onDismiss }) {
  const ext = upload.filename.split('.').pop()?.toLowerCase();
  return (
    <li className={`doc-card card3d ${upload.error ? 'status-error' : 'status-processing'}`}>
      <div className="doc-card-main">
        <span className={`file-tile kind-${ext}`} aria-hidden="true">
          <span className="file-tile-fold" />
          {ext?.toUpperCase()}
        </span>
        <div className="doc-card-text">
          <p className="doc-name" title={upload.filename}>
            {upload.filename}
          </p>
          <p className="doc-meta">
            <span className={`pill ${upload.error ? 'pill-error' : 'pill-processing'}`}>
              <span className="pill-dot" aria-hidden="true" />
              {upload.error ? 'Not uploaded' : 'Uploading'}
            </span>
          </p>
        </div>
        {upload.error && (
          <div className="doc-actions">
            <button type="button" className="icon-btn" onClick={() => onDismiss(upload.key)} aria-label="Dismiss">
              <Icon name="close" size={16} />
            </button>
          </div>
        )}
      </div>
      {upload.error ? (
        <div className="doc-error" role="alert">
          <p>{upload.error}</p>
        </div>
      ) : (
        <ProcessingSteps stage="uploading" uploadProgress={upload.progress} compact />
      )}
    </li>
  );
}
