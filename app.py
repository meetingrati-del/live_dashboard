

import re

import pandas as pd
import streamlit as st


st.set_page_config(
	page_title="Backtest report",
	page_icon=":material/query_stats:",
	layout="wide",
)


DATE_HEADERS = {"exit date", "exit datetime", "close date", "closed date", "date"}
PNL_HEADERS = {
	"pnl",
	"p and l",
	"profit loss",
	"profit and loss",
	"net pnl",
	"trade pnl",
	"net profit",
	"profit",
}


def normalize_header(header: object) -> str:
	return re.sub(r"[\W_]+", " ", str(header).strip().lower()).strip()


def find_column(columns: list[object], accepted_names: set[str]) -> object | None:
	for column in columns:
		if normalize_header(column) in accepted_names:
			return column
	return None


def format_number(value: float) -> str:
	return f"{value:,.2f}"


st.title("Backtest report", icon=":material/query_stats:")
st.caption("Trade-by-trade performance from your exit dates and realized PnL.")

with st.sidebar:
	st.subheader("Trade data")
	uploaded_file = st.file_uploader(
		"Upload a CSV file",
		type=["csv"],
		help="Include columns for exit date and PnL. Headers are matched without regard to case.",
	)
	starting_capital = st.number_input(
		"Starting capital",
		min_value=1.0,
		value=10_000.0,
		step=1_000.0,
		help="Used as the initial equity and the first drawdown peak.",
	)
	template = pd.DataFrame(
		{
			"exit date": ["2025-01-03", "2025-01-08", "2025-01-14", "2025-01-22"],
			"PnL": [250, -120, 310, -80],
		}
	)
	st.download_button(
		"Download CSV template",
		template.to_csv(index=False).encode("utf-8"),
		file_name="backtest_template.csv",
		mime="text/csv",
		icon=":material/download:",
		width="stretch",
	)

if uploaded_file is None:
	st.info("Upload a trade-history CSV to build your performance report.")
	st.markdown("Your file needs an **exit date** column and a **PnL** column.")
	st.stop()

try:
	source = pd.read_csv(uploaded_file)
except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as error:
	st.error(f"This file could not be read as a CSV: {error}")
	st.stop()

date_column = find_column(source.columns.tolist(), DATE_HEADERS)
pnl_column = find_column(source.columns.tolist(), PNL_HEADERS)
if date_column is None or pnl_column is None:
	missing = []
	if date_column is None:
		missing.append("exit date")
	if pnl_column is None:
		missing.append("PnL")
	st.error(f"Missing required column(s): {', '.join(missing)}.")
	st.caption(f"Columns found: {', '.join(map(str, source.columns)) or 'none'}")
	st.stop()

dates = pd.to_datetime(source[date_column], errors="coerce")
pnl_text = source[pnl_column].astype("string").str.strip()
parenthesized_losses = pnl_text.str.match(r"^\(.*\)$", na=False)
pnl_text = pnl_text.str.replace(r"[$,]", "", regex=True)
if parenthesized_losses.any():
	pnl_text.loc[parenthesized_losses] = "-" + pnl_text.loc[parenthesized_losses].str.slice(1, -1)
pnl = pd.to_numeric(pnl_text, errors="coerce")

trades = pd.DataFrame({"Exit date": dates, "PnL": pnl})
invalid_rows = int(trades.isna().any(axis=1).sum())
trades = trades.dropna().sort_values("Exit date", kind="stable").reset_index(drop=True)

if trades.empty:
	st.error("No valid trades found. Check that exit dates and PnL values are populated and readable.")
	st.stop()

if invalid_rows:
	st.warning(f"Skipped {invalid_rows:,} row(s) with an invalid exit date or PnL value.")

trades["Trade"] = range(1, len(trades) + 1)
trades["Equity"] = starting_capital + trades["PnL"].cumsum()
trades["Peak equity"] = trades["Equity"].clip(lower=starting_capital).cummax()
trades["Drawdown"] = trades["Equity"] - trades["Peak equity"]
trades["Drawdown %"] = trades["Equity"].div(trades["Peak equity"]).sub(1).mul(100)

wins = trades.loc[trades["PnL"] > 0, "PnL"]
losses = trades.loc[trades["PnL"] < 0, "PnL"]
breakevens = int(trades["PnL"].eq(0).sum())
win_rate = len(wins) / len(trades) * 100
average_win = float(wins.mean()) if not wins.empty else None
average_loss = float(losses.mean()) if not losses.empty else None
risk_reward = average_win / abs(average_loss) if average_win is not None and average_loss else None
gross_loss = abs(float(losses.sum())) if not losses.empty else 0.0
profit_factor = float(wins.sum()) / gross_loss if gross_loss else None
net_pnl = float(trades["PnL"].sum())
max_drawdown = float(trades["Drawdown"].min())
max_drawdown_pct = float(trades["Drawdown %"].min())

yearly = (
	trades.assign(Year=trades["Exit date"].dt.year)
	.groupby("Year", as_index=False)["PnL"]
	.sum()
)
monthly = (
	trades.assign(Month=trades["Exit date"].dt.to_period("M").astype(str))
	.groupby("Month", as_index=False)["PnL"]
	.sum()
)

st.caption(
	f"{len(trades):,} valid trades · {trades['Exit date'].min():%d %b %Y} to "
	f"{trades['Exit date'].max():%d %b %Y} · values shown in the units of your PnL column"
)

st.subheader("Performance summary")
first_row = st.columns(4)
first_row[0].metric("Net PnL", format_number(net_pnl))
first_row[1].metric("Win rate", f"{win_rate:.1f}%")
first_row[2].metric("Risk / reward", format_number(risk_reward) if risk_reward is not None else "N/A")
first_row[3].metric("Profit factor", format_number(profit_factor) if profit_factor is not None else "N/A")

second_row = st.columns(4)
second_row[0].metric("Trades", f"{len(trades):,}")
second_row[1].metric("Expectancy / trade", format_number(float(trades["PnL"].mean())))
second_row[2].metric("Max drawdown", format_number(max_drawdown))
second_row[3].metric("Ending equity", format_number(float(trades["Equity"].iloc[-1])))

st.caption(
	f"Win rate counts positive trades out of all valid trades, including {breakevens:,} breakeven trade(s). "
	"Risk / reward is average winning PnL divided by the absolute average losing PnL."
)

st.subheader("Equity and drawdown")
st.line_chart(
	trades,
	x="Exit date",
	y="Equity",
	x_label="Exit date",
	y_label="Equity",
	alt="Equity curve from starting capital through each completed trade",
)
st.area_chart(
	trades,
	x="Exit date",
	y="Drawdown",
	x_label="Exit date",
	y_label="Drawdown",
	color="#C55353",
	alt="Drawdown from the highest equity reached so far",
)
st.caption(f"Worst peak-to-trough drawdown: {format_number(max_drawdown)} ({max_drawdown_pct:.2f}%).")

st.subheader("PnL by period")
year_column, month_column = st.columns(2)
with year_column:
	st.markdown("**Yearly**")
	st.bar_chart(yearly, x="Year", y="PnL", x_label="Year", y_label="PnL", alt="Total PnL by calendar year")
	st.dataframe(yearly, hide_index=True, alt="Yearly PnL totals")
with month_column:
	st.markdown("**Monthly**")
	st.bar_chart(monthly, x="Month", y="PnL", x_label="Month", y_label="PnL", alt="Total PnL by calendar month")
	st.dataframe(monthly, hide_index=True, alt="Monthly PnL totals")

with st.expander("Trade log"):
	report = trades[["Trade", "Exit date", "PnL", "Equity", "Drawdown", "Drawdown %"]].copy()
	st.dataframe(report, hide_index=True, alt="Trades sorted by exit date with cumulative equity and drawdown")
	st.download_button(
		"Download trade report",
		report.to_csv(index=False).encode("utf-8"),
		file_name="backtest_report.csv",
		mime="text/csv",
		icon=":material/download:",
	)


