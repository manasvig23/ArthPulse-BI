import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatMoney } from "../format.js";

const COLORS = ["#26765b", "#65cba6", "#e9b646", "#db5b5b", "#6b8e9e"];
const axisTick = { fill: "var(--muted)", fontSize: 11 };
const tooltipStyle = {
  background: "var(--card)", border: "1px solid var(--line)",
  borderRadius: 8, fontSize: 12, color: "var(--ink)",
};
const tooltipText = { color: "var(--ink)" };
const axisMoney = v => (v >= 100000 ? `${(v / 100000).toFixed(0)}L` : v.toLocaleString("en-IN"));

/** labels: ["Mar", ...]   series: [{ name, values: [...] }]   type: "bar" | "line" */
export function TrendChart({ labels, series, type = "bar" }) {
  const rows = labels.map((label, i) => {
    const row = { label };
    series.forEach(s => { row[s.name] = s.values[i]; });
    return row;
  });
  const Chart = type === "line" ? LineChart : BarChart;

  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
          <XAxis dataKey="label" tick={axisTick} axisLine={false} tickLine={false} />
          <YAxis tick={axisTick} tickFormatter={axisMoney} axisLine={false} tickLine={false} width={44} />
          <Tooltip formatter={formatMoney} contentStyle={tooltipStyle} itemStyle={tooltipText} labelStyle={tooltipText} cursor={{ opacity: 0.15 }} />
          {series.length > 1 && <Legend />}
          {series.map((s, i) =>
            type === "line"
              ? <Line key={s.name} type="monotone" dataKey={s.name} stroke={COLORS[i]} strokeWidth={2.5} dot={{ r: 3 }} />
              : <Bar key={s.name} dataKey={s.name} fill={COLORS[i]} radius={[6, 6, 2, 2]} />
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

/** items: { "Apex Packaging": 410000, ... } */
export function DonutChart({ items }) {
  const data = Object.entries(items || {}).map(([name, value]) => ({ name, value }));
  if (!data.length) return <p className="empty">No data for this period.</p>;

  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={55} outerRadius={88} paddingAngle={2}>
            {data.map((d, i) => <Cell key={d.name} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip formatter={formatMoney} contentStyle={tooltipStyle} itemStyle={tooltipText} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

/** items: { "0–30 days": 2494210, ... }  (one bar per bucket) */
export function BucketChart({ items }) {
  const data = Object.entries(items || {}).map(([name, value]) => ({ name, value }));
  if (!data.length) return <p className="empty">No data for this period.</p>;

  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
          <XAxis dataKey="name" tick={axisTick} axisLine={false} tickLine={false} />
          <YAxis tick={axisTick} tickFormatter={axisMoney} axisLine={false} tickLine={false} width={44} />
          <Tooltip formatter={formatMoney} contentStyle={tooltipStyle} itemStyle={tooltipText} labelStyle={tooltipText} cursor={{ opacity: 0.15 }} />
          <Bar dataKey="value" name="Outstanding" radius={[6, 6, 2, 2]}>
            {data.map((d, i) => <Cell key={d.name} fill={["#65cba6", "#e9b646", "#e08a4a", "#db5b5b"][i % 4]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
