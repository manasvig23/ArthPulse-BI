from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from . import compliance, forecasts, quality, recommendations, summaries
from .database import SessionLocal
from .explainability import explain_sales_drivers
from .tally_sync import last_sync

load_dotenv()


def _normalise_period(period: str) -> str:
    """Return a supported reporting period."""
    if period not in summaries.PERIOD_DAYS:
        return "monthly"
    return period


def _context(period: str) -> dict:
    """Collect dashboard data used to ground an assistant response."""
    period = _normalise_period(period)
    db = SessionLocal()

    try:
        summary = summaries.build_summary(db, period)
        recs = recommendations.list_recommendations(db)
        drivers = explain_sales_drivers(db, period)
        quality_data = quality.build_quality(db)
        forecast_data = forecasts.build_forecasts(db)
        compliance_data = compliance.build_compliance(db)
        sync_data = last_sync(db)

        sales = summary.get("sales") or {}
        cashflow = summary.get("cashflow") or {}
        inventory = summary.get("inventory") or {}
        purchases = summary.get("purchases") or {}

        forecast_sales = forecast_data.get("sales") or {}
        forecast_cash = forecast_data.get("cash") or {}

        return {
            "period": summary.get("period", period),
            "window": summary.get("window"),
            "label": summary.get("label"),
            "last_sync": sync_data,
            "quality_warnings": quality_data.get("warnings") or [],
            "overview": summary.get("overview") or {},
            "sales": {
                key: value
                for key, value in sales.items()
                if key != "trend"
            },
            "purchases": purchases,
            "inventory": inventory,
            "cashflow": cashflow,
            "compliance_summary": compliance_data.get("summary") or {},
            "compliance_headlines": [
                row.get("headline")
                for row in compliance_data.get("rules", [])
                if row.get("headline")
            ],
            "recommendations": [
                {
                    "title": row.get("title", "Untitled recommendation"),
                    "reason": row.get("reason", ""),
                }
                for row in recs[:8]
            ],
            "forecast": {
                "next_month_sales": forecast_sales.get("forecast"),
                "method": forecast_sales.get("method"),
                "expected_cash_in": forecast_cash.get("expected_in"),
                "expected_cash_out": forecast_cash.get("expected_out"),
            },
            "drivers": drivers,
        }

    finally:
        db.close()


def _needs_followup(question: str) -> str | None:
    """Ask for clarification when the question is too vague to answer."""
    q = question.strip().lower()

    if q in {"hi", "hello", "hey", "help"}:
        return (
            "Ask me about sales performance, sales drivers, slow-moving "
            "stock, overdue invoices, supplier prices, GST/TDS compliance, "
            "or the sales forecast."
        )

    if len(q) < 8:
        return (
            "Which period, customer, product, invoice, or business metric "
            "should I look at?"
        )

    return None


def _money(value) -> str:
    """Format a known numeric value as Indian rupees."""
    if value is None:
        return "not available"

    try:
        return f"₹{round(float(value)):,}"
    except (TypeError, ValueError, OverflowError):
        return "not available"


def _period_footer(ctx: dict) -> str:
    """Append the reporting window and available data timestamp."""
    window = ctx.get("window") or {}
    sync = ctx.get("last_sync") or {}
    drivers = ctx.get("drivers") or {}

    timestamp = sync.get("finished_at") or drivers.get("as_of")
    period_label = ctx.get("label") or ctx.get("period") or "Selected period"

    footer = (
        f"\n\nPeriod: {period_label} "
        f"({window.get('start', 'unknown')} to "
        f"{window.get('end', 'unknown')}). "
        f"Data as of {timestamp or 'the available reference date'}."
    )

    warnings = ctx.get("quality_warnings") or []
    if warnings:
        footer += f"\nData quality note: {warnings[0]}"

    return footer


def _sales_driver_answer(ctx: dict) -> str:
    """Explain ranked features without claiming causation or direction."""
    driver_data = ctx.get("drivers") or {}
    drivers = driver_data.get("drivers") or []

    if not drivers:
        explanation = driver_data.get("plain_english") or (
            "There is not enough information in the selected reporting "
            "period to rank sales-related factors reliably."
        )
        return explanation + _period_footer(ctx)

    lines = []

    for index, driver in enumerate(drivers[:6], start=1):
        factor = driver.get("factor", "Unknown factor")
        score = driver.get("impact_score")

        try:
            formatted_score = f"{float(score):.2f}"
        except (TypeError, ValueError, OverflowError):
            formatted_score = None

        if formatted_score is None:
            lines.append(f"{index}. {factor}")
        else:
            lines.append(
                f"{index}. {factor} — importance score {formatted_score}"
            )

    method = driver_data.get("method", "Not available")
    explanation = driver_data.get("plain_english", "")

    answer = (
        "The sales-driver analysis ranked these features as the strongest "
        "contributors to the model's sales predictions:\n"
        + "\n".join(lines)
        + f"\n\nAnalysis method: {method}."
    )

    if explanation:
        answer += f"\n{explanation}"

    answer += (
        "\n\nImportant: these are model-based importance rankings. "
        "They do not, by themselves, show whether a factor increased "
        "or decreased sales, or prove that it caused a change."
    )

    return answer + _period_footer(ctx)


def _rule_answer(question: str, ctx: dict) -> str:
    """Answer common business questions using collected dashboard data."""
    q = question.lower()

    overview = ctx.get("overview") or {}
    inventory = ctx.get("inventory") or {}
    cashflow = ctx.get("cashflow") or {}
    purchases = ctx.get("purchases") or {}
    forecast = ctx.get("forecast") or {}
    recommendations_data = ctx.get("recommendations") or []
    compliance_summary = ctx.get("compliance_summary") or {}

    footer = _period_footer(ctx)

    # Sales-driver and explainability questions.
    driver_terms = (
        "shap",
        "sales driver",
        "sales factor",
        "explain sales",
        "sales explain",
        "which factor",
        "which feature",
        "driving sales",
        "drivers",
        "feature importance",
        "affect sales",
    )

    if any(term in q for term in driver_terms):
        return _sales_driver_answer(ctx)

    # Explain changes in sales.
    if "why" in q and "sales" in q:
        net_sales = overview.get("net_sales")
        growth = overview.get("growth")
        driver_data = ctx.get("drivers") or {}

        answer = f"Net sales for this period are {_money(net_sales)}."

        if growth is not None:
            direction = (
                "up" if growth > 0
                else "down" if growth < 0
                else "unchanged"
            )
            answer += (
                f" Compared with the previous period, sales are "
                f"{direction} by {abs(growth):.1f}%."
            )
        else:
            answer += " A percentage comparison is not available."

        explanation = driver_data.get("plain_english")
        if explanation:
            answer += f"\n\nSales-driver analysis: {explanation}"

        answer += (
            "\nThese ranked features indicate associations in the model; "
            "they do not establish the cause or direction of the sales change."
        )

        return answer + footer

    # Inactive customers.
    if any(
        term in q
        for term in (
            "inactive",
            "not purchased",
            "60 days",
            "lapsed customer",
        )
    ):
        matches = [
            row for row in recommendations_data
            if any(
                term in row.get("title", "").lower()
                for term in (
                    "no purchase",
                    "declin",
                    "inactive",
                    "customer",
                )
            )
        ]

        if not matches:
            return (
                "I couldn't find a matching inactive-customer recommendation "
                "in the current recommendation list."
                + footer
            )

        lines = [
            f"- {row['title']}: {row['reason']}"
            if row.get("reason")
            else f"- {row['title']}"
            for row in matches[:6]
        ]

        return (
            "Customer recommendations to review:\n"
            + "\n".join(lines)
            + footer
        )

    # Slow-moving or non-moving stock.
    if "slow" in q or "non-moving" in q or "non moving" in q:
        efficiency = inventory.get("efficiency") or []

        efficiency_lines = [
            f"- {item[0]}: {item[1]}"
            for item in efficiency
            if isinstance(item, (list, tuple)) and len(item) >= 2
        ]

        slow_items = inventory.get("high_value_slow") or []
        item_lines = [
            f"- {row[0]} ({row[1]}): {_money(row[2])}, {row[3]}"
            for row in slow_items[:6]
            if isinstance(row, (list, tuple)) and len(row) >= 4
        ]

        answer = (
            f"Current stock value: {_money(inventory.get('stock_value'))}."
        )

        if efficiency_lines:
            answer += (
                "\n\nInventory indicators:\n"
                + "\n".join(efficiency_lines)
            )

        if item_lines:
            answer += (
                "\n\nHigher-value slow/non-moving items:\n"
                + "\n".join(item_lines)
            )
        else:
            answer += (
                "\n\nNo matching high-value slow/non-moving items were "
                "returned by the current inventory summary."
            )

        return answer + footer

    # Receivables and overdue invoices.
    if "overdue" in q or "receivable" in q or "invoice" in q:
        answer = (
            f"Outstanding receivables: "
            f"{_money(cashflow.get('receivables'))}.\n"
            f"Overdue receivables: "
            f"{_money(cashflow.get('overdue_receivables'))}.\n"
            f"Largest debtor: "
            f"{cashflow.get('top_debtor', 'not available')} "
            f"({_money(cashflow.get('top_debtor_amount'))})."
        )

        ageing = cashflow.get("ageing") or {}
        if ageing:
            answer += "\n\nReceivables ageing:"
            answer += "\n" + "\n".join(
                f"- {bucket}: {_money(amount)}"
                for bucket, amount in ageing.items()
            )

        return answer + footer

    # Supplier price changes.
    if "supplier" in q and any(
        term in q for term in ("price", "rate", "cost")
    ):
        moves = purchases.get("price_moves") or []

        if not moves:
            return (
                "The current purchase summary has no supplier price "
                "movements to report. Repeat purchase history may be "
                "insufficient."
                + footer
            )

        lines = [
            f"- Supplier: {row[0]}; product: {row[2]}; movement: {row[1]}"
            for row in moves
            if isinstance(row, (list, tuple)) and len(row) >= 3
        ]

        return "Supplier price movements:\n" + "\n".join(lines) + footer

    # Reorder and stock-review recommendations.
    if ("stock" in q and "review" in q) or "reorder" in q:
        matches = [
            row for row in recommendations_data
            if any(
                term in row.get("title", "").lower()
                for term in ("reorder", "stock", "clear", "inventory")
            )
        ]

        if not matches:
            return (
                "No matching stock-review recommendations were found."
                + footer
            )

        lines = [
            f"- {row['title']}: {row['reason']}"
            if row.get("reason")
            else f"- {row['title']}"
            for row in matches[:6]
        ]

        return "Stock recommendations:\n" + "\n".join(lines) + footer

    # GST/TDS and other compliance questions.
    if any(term in q for term in ("gst", "tds", "compliance", "269")):
        headlines = ctx.get("compliance_headlines") or []
        findings = compliance_summary.get("findings")
        flagged_amount = compliance_summary.get("amount_flagged")

        answer = "Compliance summary:\n"

        if findings is not None:
            answer += f"- Findings: {findings}\n"

        if flagged_amount is not None:
            answer += f"- Amount flagged: {_money(flagged_amount)}\n"

        if headlines:
            answer += (
                "\nChecks to review:\n"
                + "\n".join(f"- {headline}" for headline in headlines)
            )
        elif findings is None and flagged_amount is None:
            answer += (
                "The current compliance summary does not contain these totals."
            )

        return answer + footer

    # Forecast questions.
    if any(
        term in q
        for term in (
            "forecast",
            "next month",
            "future sales",
            "predict sales",
        )
    ):
        next_sales = forecast.get("next_month_sales")

        if next_sales is None:
            return (
                "There is not enough information in the current forecast "
                "to report a next-month sales estimate."
                + footer
            )

        answer = (
            f"Forecast sales for next month: {_money(next_sales)}.\n"
            f"Forecast method: {forecast.get('method') or 'not specified'}.\n"
            f"Expected cash in: "
            f"{_money(forecast.get('expected_cash_in'))}.\n"
            f"Expected cash out: "
            f"{_money(forecast.get('expected_cash_out'))}."
        )

        return answer + footer

    # Sales performance questions.
    if "sales" in q or "revenue" in q:
        net_sales = overview.get("net_sales")
        growth = overview.get("growth")

        answer = f"Net sales for this period: {_money(net_sales)}."

        if growth is not None:
            answer += (
                f"\nChange versus the previous period: {growth:.1f}%."
            )

        answer += (
            "\n\nYou can ask me to rank sales drivers, explain sales changes, "
            "or compare inventory, receivables and compliance indicators."
        )

        return answer + footer

    # General business overview.
    return (
        f"Net sales: {_money(overview.get('net_sales'))}.\n"
        f"Receivables: {_money(overview.get('receivables'))}.\n"
        f"Overdue receivables: {_money(overview.get('overdue'))}.\n"
        f"Stock value: {_money(overview.get('stock_value'))}.\n"
        f"Sales less purchases (margin proxy): "
        f"{_money(overview.get('sales_less_purchases'))}.\n\n"
        "Ask about sales drivers, slow-moving stock, overdue invoices, "
        "supplier price changes, compliance or forecasts."
        + footer
    )


def answer_query(user_prompt: str, period: str = "monthly") -> dict:
    """Return a grounded answer, using Gemini when configured."""
    period = _normalise_period(period)
    user_prompt = user_prompt.strip()

    followup = _needs_followup(user_prompt)
    context = _context(period)

    if followup:
        return {
            "status": "followup",
            "answer": followup,
            "period": period,
            "window": context.get("window"),
            "data_as_of": (
                (context.get("last_sync") or {}).get("finished_at")
            ),
            "grounded_in_data": True,
            "links": ["overview"],
        }

    grounded_answer = _rule_answer(user_prompt, context)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not api_key:
        return {
            "status": "success",
            "answer": grounded_answer,
            "period": period,
            "window": context.get("window"),
            "data_as_of": (
                (context.get("last_sync") or {}).get("finished_at")
            ),
            "grounded_in_data": True,
            "engine": "rules",
            "links": ["overview", "alerts"],
        }

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = f"""You are ArthPulse, a business analytics assistant.

Answer using ONLY the supplied CONTEXT. Never invent a number or imply
that missing data is known. Use INR for rupee amounts. State the reporting
period and data timestamp when available. Format lists with line breaks.

For sales-driver questions:
- Explain that the ranked features are model-based associations.
- Do not claim that importance scores prove causation.
- Do not claim a feature increased or decreased sales unless the context
  explicitly provides that direction.
- Never describe feature importance as a causal explanation.
- Do not expose raw model internals unless the user specifically asks
  about the analysis method.

If the context does not contain enough information, say so. Keep the
answer clear and concise.

CONTEXT:
{json.dumps(context, default=str)[:12000]}

REFERENCE ANSWER:
{grounded_answer}

QUESTION:
{user_prompt}
"""

        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.15,
                "max_output_tokens": 700,
            },
        )

        answer = (response.text or "").strip() or grounded_answer

        warnings = context.get("quality_warnings") or []
        if warnings and warnings[0] not in answer:
            answer += "\n\nData quality note: " + warnings[0]

        return {
            "status": "success",
            "answer": answer,
            "period": period,
            "window": context.get("window"),
            "data_as_of": (
                (context.get("last_sync") or {}).get("finished_at")
            ),
            "grounded_in_data": True,
            "engine": "gemini+context",
            "links": ["overview"],
        }

    except Exception:
        # Keep the dashboard-grounded rule answer available if Gemini fails.
        return {
            "status": "success",
            "answer": grounded_answer,
            "period": period,
            "window": context.get("window"),
            "data_as_of": (
                (context.get("last_sync") or {}).get("finished_at")
            ),
            "grounded_in_data": True,
            "engine": "rules-fallback",
            "links": ["overview"],
        }


class ArthPulseAIService:
    """Compatibility wrapper used by the FastAPI endpoint."""

    def answer_query(self, user_prompt: str, period: str = "monthly"):
        return answer_query(user_prompt, period)


ai_service = ArthPulseAIService()
