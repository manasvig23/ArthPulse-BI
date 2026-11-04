import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatMoney } from "../format.js";

const COLORS = ["#26765b", "#65cba6", "#e9b646", "#db5b5b", "#6b8e9e"];
const BUCKET_COLORS = ["#65cba6", "#e9b646", "#e08a4a", "#db5b5b"];

const axisTick = { fill: "var(--muted)", fontSize: 11 };

const tooltipStyle = {
  background: "var(--card)",
  border: "1px solid var(--line)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--ink)",
};

const tooltipText = { color: "var(--ink)" };

const axisMoney = value => {
  const number = Number(value) || 0;

  if (Math.abs(number) >= 10000000) {
    return `${(number / 10000000).toFixed(1)}Cr`;
  }

  if (Math.abs(number) >= 100000) {
    return `${(number / 100000).toFixed(1)}L`;
  }

  if (Math.abs(number) >= 1000) {
    return `${(number / 1000).toFixed(1)}K`;
  }

  return number.toLocaleString("en-IN");
};

function ChartEmpty({ message = "No data for this period." }) {
  return <p className="empty">{message}</p>;
}

/**
 * A clickable legend shared by the trend charts.
 * Clicking a legend entry hides or restores its series.
 */
function InteractiveLegend({ payload = [], hiddenKeys, onToggle }) {
  return (
    <div
      className="interactive-chart-legend"
      role="group"
      aria-label="Toggle chart data series"
    >
      {payload.map(entry => {
        const key = entry.dataKey || entry.value;
        const hidden = hiddenKeys.has(key);

        return (
          <button
            key={key}
            type="button"
            className={`interactive-legend-item${hidden ? " is-hidden" : ""}`}
            onClick={() => onToggle(key)}
            aria-pressed={!hidden}
            title={`${hidden ? "Show" : "Hide"} ${entry.value}`}
          >
            <span
              className="legend-swatch"
              style={{ backgroundColor: entry.color || entry.payload?.stroke }}
            />
            <span>{entry.value}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * labels: ["Mar", "Apr", ...]
 * series: [{ name: "Net sales", values: [...] }]
 * type: "bar" | "line"
 *
 * Supports clickable legends, exact-value tooltips and selection of a period.
 */
export function TrendChart({ labels = [], series = [], type = "bar" }) {
  const [hiddenKeys, setHiddenKeys] = useState(() => new Set());
  const [selectedLabel, setSelectedLabel] = useState(null);

  const rows = useMemo(() => {
    return (labels || []).map((label, index) => {
      const row = { label };

      (series || []).forEach(item => {
        const value = item.values?.[index];
        row[item.name] =
          value === null || value === undefined || value === ""
            ? null
            : Number.isFinite(Number(value))
              ? Number(value)
              : null;
      });

      return row;
    });
  }, [labels, series]);

  const visibleSeries = series.filter(item => !hiddenKeys.has(item.name));
  const selectedRow = rows.find(row => row.label === selectedLabel);

  const toggleSeries = key => {
    setHiddenKeys(previous => {
      const next = new Set(previous);

      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }

      return next;
    });
  };

  if (!rows.length || !series.length) {
    return <ChartEmpty />;
  }

  const Chart = type === "line" ? LineChart : BarChart;

  return (
    <div>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <Chart
            data={rows}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            onClick={state => {
              const row = state?.activePayload?.[0]?.payload;
              if (row?.label !== undefined) {
                setSelectedLabel(row.label);
              }
            }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--line)"
              vertical={false}
            />

            <XAxis
              dataKey="label"
              tick={axisTick}
              axisLine={false}
              tickLine={false}
            />

            <YAxis
              tick={axisTick}
              tickFormatter={axisMoney}
              axisLine={false}
              tickLine={false}
              width={52}
            />

            <Tooltip
              formatter={(value, name) => [
                value == null ? "No data" : formatMoney(value),
                name,
              ]}
              labelFormatter={label => `Period: ${label}`}
              contentStyle={tooltipStyle}
              itemStyle={tooltipText}
              labelStyle={tooltipText}
              cursor={{ fill: "var(--line)", opacity: 0.35 }}
            />

            {series.length > 1 && (
              <Legend
                verticalAlign="bottom"
                content={
                  <InteractiveLegend
                    hiddenKeys={hiddenKeys}
                    onToggle={toggleSeries}
                  />
                }
              />
            )}

            {visibleSeries.map(item => {
              const originalIndex = series.findIndex(
                entry => entry.name === item.name
              );
              const color = COLORS[originalIndex % COLORS.length];

              return type === "line" ? (
                <Line
                  key={item.name}
                  type="monotone"
                  dataKey={item.name}
                  name={item.name}
                  stroke={color}
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                  activeDot={{ r: 6, cursor: "pointer" }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ) : (
                <Bar
                  key={item.name}
                  dataKey={item.name}
                  name={item.name}
                  fill={color}
                  radius={[6, 6, 2, 2]}
                  isAnimationActive={false}
                />
              );
            })}
          </Chart>
        </ResponsiveContainer>
      </div>

      {selectedRow && (
        <div className="chart-selection" aria-live="polite">
          <div>
            <strong>{selectedRow.label}</strong>
            <div className="chart-selection-values">
              {visibleSeries.map(item => (
                <span key={item.name}>
                  {item.name}:{" "}
                  <strong>
                    {selectedRow[item.name] == null
                      ? "No data"
                      : formatMoney(selectedRow[item.name])}
                  </strong>
                </span>
              ))}
            </div>
          </div>

          <button
            type="button"
            className="ghost-button"
            onClick={() => setSelectedLabel(null)}
          >
            Clear selection
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * items: { "Apex Packaging": 410000, ... }
 *
 * Supports clickable legend entries and slice selection.
 */
export function DonutChart({ items = {} }) {
  const [hiddenKeys, setHiddenKeys] = useState(() => new Set());
  const [selectedName, setSelectedName] = useState(null);

  const data = useMemo(
    () =>
      Object.entries(items || {})
        .map(([name, value]) => ({
          name,
          value: Number(value),
        }))
        .filter(item => Number.isFinite(item.value)),
    [items]
  );

  const visibleData = data.filter(item => !hiddenKeys.has(item.name));
  const selectedItem = data.find(item => item.name === selectedName);

  if (!data.length) {
    return <ChartEmpty />;
  }

  const toggleItem = name => {
    setHiddenKeys(previous => {
      const next = new Set(previous);

      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }

      return next;
    });

    if (name === selectedName) {
      setSelectedName(null);
    }
  };

  return (
    <div>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={visibleData}
              dataKey="value"
              nameKey="name"
              innerRadius={52}
              outerRadius={82}
              paddingAngle={2}
              onClick={entry => setSelectedName(entry.name)}
              isAnimationActive={false}
            >
              {visibleData.map(item => (
                <Cell
                  key={item.name}
                  fill={COLORS[data.findIndex(row => row.name === item.name) % COLORS.length]}
                  cursor="pointer"
                  stroke={
                    selectedName === item.name
                      ? "var(--ink)"
                      : "var(--card)"
                  }
                  strokeWidth={selectedName === item.name ? 3 : 1}
                />
              ))}
            </Pie>

            <Tooltip
              formatter={(value, name) => [formatMoney(value), name]}
              contentStyle={tooltipStyle}
              itemStyle={tooltipText}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div
        className="interactive-chart-legend"
        role="group"
        aria-label="Toggle supplier spend categories"
      >
        {data.map((item, index) => {
          const hidden = hiddenKeys.has(item.name);

          return (
            <button
              key={item.name}
              type="button"
              className={`interactive-legend-item${hidden ? " is-hidden" : ""}`}
              onClick={() => toggleItem(item.name)}
              aria-pressed={!hidden}
              title={`${hidden ? "Show" : "Hide"} ${item.name}`}
            >
              <span
                className="legend-swatch"
                style={{ backgroundColor: COLORS[index % COLORS.length] }}
              />
              <span>{item.name}</span>
            </button>
          );
        })}
      </div>

      {selectedItem && !hiddenKeys.has(selectedName) && (
        <div className="chart-selection" aria-live="polite">
          <span>
            <strong>{selectedItem.name}</strong>:{" "}
            {formatMoney(selectedItem.value)}
          </span>
          <button
            type="button"
            className="ghost-button"
            onClick={() => setSelectedName(null)}
          >
            Clear selection
          </button>
        </div>
      )}

      {!visibleData.length && (
        <p className="empty">All categories are hidden. Use the legend to restore one.</p>
      )}
    </div>
  );
}

/**
 * items: { "0–30 days": 2494210, ... }
 *
 * Clicking a bar selects an ageing bucket and displays its amount.
 */
export function BucketChart({ items = {} }) {
  const [selectedName, setSelectedName] = useState(null);

  const data = useMemo(
    () =>
      Object.entries(items || {})
        .map(([name, value]) => ({
          name,
          value: Number(value),
        }))
        .filter(item => Number.isFinite(item.value)),
    [items]
  );

  const selectedItem = data.find(item => item.name === selectedName);

  if (!data.length) {
    return <ChartEmpty />;
  }

  return (
    <div>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--line)"
              vertical={false}
            />

            <XAxis
              dataKey="name"
              tick={axisTick}
              axisLine={false}
              tickLine={false}
            />

            <YAxis
              tick={axisTick}
              tickFormatter={axisMoney}
              axisLine={false}
              tickLine={false}
              width={52}
            />

            <Tooltip
              formatter={(value, name) => [formatMoney(value), name]}
              labelFormatter={label => `Ageing bucket: ${label}`}
              contentStyle={tooltipStyle}
              itemStyle={tooltipText}
              labelStyle={tooltipText}
              cursor={{ fill: "var(--line)", opacity: 0.35 }}
            />

            <Bar
              dataKey="value"
              name="Outstanding"
              radius={[6, 6, 2, 2]}
              onClick={entry => setSelectedName(entry.name)}
              isAnimationActive={false}
            >
              {data.map((item, index) => (
                <Cell
                  key={item.name}
                  fill={BUCKET_COLORS[index % BUCKET_COLORS.length]}
                  cursor="pointer"
                  stroke={
                    selectedName === item.name
                      ? "var(--ink)"
                      : "transparent"
                  }
                  strokeWidth={selectedName === item.name ? 2 : 0}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {selectedItem && (
        <div className="chart-selection" aria-live="polite">
          <span>
            <strong>{selectedItem.name}</strong> ageing bucket —{" "}
            {formatMoney(selectedItem.value)}
          </span>
          <button
            type="button"
            className="ghost-button"
            onClick={() => setSelectedName(null)}
          >
            Clear selection
          </button>
        </div>
      )}
    </div>
  );
}
