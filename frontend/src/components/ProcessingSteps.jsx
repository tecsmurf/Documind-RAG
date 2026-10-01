/**
 * Real pipeline progress. "Uploading" comes from the browser's upload progress;
 * every later step comes from the document's `processing_stage` on the server.
 */
import { STEPS, stepIndex } from '../lib/steps';
import Icon from './Icon';


export default function ProcessingSteps({ stage, uploadProgress, compact = false }) {
  const current = stepIndex(stage);
  return (
    <ol className={`steps ${compact ? 'steps-compact' : ''}`} aria-label="Processing progress">
      {STEPS.map((step, i) => {
        const state = i < current || stage === 'ready' ? 'done' : i === current ? 'active' : 'todo';
        return (
          <li key={step.key} className={`step step-${state}`} aria-current={state === 'active' ? 'step' : undefined}>
            <span className="step-dot" aria-hidden="true">
              {state === 'done' ? <Icon name="check" size={11} strokeWidth={2.6} /> : null}
            </span>
            <span className="step-label">
              {step.label}
              {step.key === 'uploading' && state === 'active' && uploadProgress != null ? ` ${uploadProgress}%` : ''}
            </span>
            <span className="visually-hidden">{state === 'done' ? ' (done)' : state === 'active' ? ' (in progress)' : ''}</span>
          </li>
        );
      })}
    </ol>
  );
}
