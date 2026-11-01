import { useMemo, useState } from "react";

/**
 * Searchable table.
 *   columns:   [{ header, cell(row), className?(row) }]
 *   rows:      array of arrays straight from the API
 *   selection: optional { ids:Set, setIds, getId(row) } -> adds checkboxes
 */
export default function DataTable({
  label, title, columns, rows, placeholder, extra, action, selection,
}) {
  const [term, setTerm] = useState("");

  const visible = useMemo(() => {
    const t = term.trim().toLowerCase();
    return t ? rows.filter(r => r.join(" ").toLowerCase().includes(t)) : rows;
  }, [rows, term]);

  const allChecked = selection && visible.length > 0
    && visible.every(r => selection.ids.has(selection.getId(r)));

  const toggleAll = () => {
    const next = new Set(selection.ids);
    visible.forEach(r => (allChecked ? next.delete(selection.getId(r)) : next.add(selection.getId(r))));
    selection.setIds(next);
  };

  const toggleOne = row => {
    const next = new Set(selection.ids);
    const id = selection.getId(row);
    next.has(id) ? next.delete(id) : next.add(id);
    selection.setIds(next);
  };

  const span = columns.length + (selection ? 1 : 0);

  return (
    <article className="card">
      <div className="table-toolbar">
        <div>
          <p className="card-label">{label}</p>
          <h2>{title}</h2>
        </div>
        <div className="toolbar-actions">
          {extra}
          {action}
          <input
            className="search"
            value={term}
            onChange={e => setTerm(e.target.value)}
            placeholder={placeholder}
          />
        </div>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {selection && (
                <th><input type="checkbox" checked={!!allChecked} onChange={toggleAll} aria-label="Select all" /></th>
              )}
              {columns.map(c => <th key={c.header}>{c.header}</th>)}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr><td colSpan={span}>No matching records.</td></tr>
            )}
            {visible.map((row, i) => (
              <tr key={i}>
                {selection && (
                  <td>
                    <input
                      type="checkbox"
                      checked={selection.ids.has(selection.getId(row))}
                      onChange={() => toggleOne(row)}
                    />
                  </td>
                )}
                {columns.map(c => (
                  <td key={c.header} className={c.className ? c.className(row) : ""}>{c.cell(row)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
