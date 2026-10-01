/** DocuMind mark: two stacked pages with a spark, drawn in CSS 3D. */
export default function Logo({ size = 'md', withText = true }) {
  return (
    <span className={`logo logo-${size}`}>
      <span className="logo-mark" aria-hidden="true">
        <span className="logo-page back" />
        <span className="logo-page front" />
        <span className="logo-spark" />
      </span>
      {withText && (
        <span className="logo-text">
          Docu<span>Mind</span>
        </span>
      )}
    </span>
  );
}
