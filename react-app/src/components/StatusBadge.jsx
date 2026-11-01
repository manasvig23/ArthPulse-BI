import { statusType } from "../format.js";

export default function StatusBadge({ value }) {
  return <span className={`status ${statusType(value)}`}>{value}</span>;
}
