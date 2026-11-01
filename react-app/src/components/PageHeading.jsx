export default function PageHeading({ eyebrow, title, subtext, children }) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="subtext">{subtext}</p>
      </div>
      {children}
    </div>
  );
}
