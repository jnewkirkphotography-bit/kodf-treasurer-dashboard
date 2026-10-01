"""KODF Treasurer Dashboard — fictional demonstration data only.

Requires Streamlit. Run: uv run streamlit run streamlit_app.py
No credentials, external connections, uploads, or persistent edits.
"""
import csv
import io
from datetime import date, timedelta
import streamlit as st

st.set_page_config(page_title="KODF | Treasurer Dashboard", page_icon="📊", layout="wide")

MONTHS = ["2026-06", "2026-07", "2026-08", "2026-09"]
INCOME = {"Rentals": [3400, 4100, 3650, 4550], "Donations": [1250, 900, 1600, 1100],
          "Grants": [0, 5000, 0, 2500], "B2B": [450, 600, 500, 700]}
EXPENSES = {"Utilities": [650, 720, 810, 690], "Maintenance": [400, 1200, 350, 650],
            "Programs": [800, 950, 1100, 850], "Administration": [300, 300, 325, 325],
            "Processing fees": [100, 125, 115, 140]}
BUDGETS = {"Utilities": 750, "Maintenance": 600, "Programs": 1000,
           "Administration": 350, "Processing fees": 130}

def make_transactions():
    rows = []
    for i, month in enumerate(MONTHS):
        for kind, groups in [("Income", INCOME), ("Expense", EXPENSES)]:
            for category, values in groups.items():
                amount = values[i]
                if amount:
                    rows.append({"Date": f"{month}-15", "Type": kind,
                                 "Category": category, "Amount": amount,
                                 "Description": f"Sample monthly {category.lower()} total"})
    return rows

TRANSACTIONS = make_transactions()

def csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")

def money(value):
    return f"${value:,.2f}"

def show_table(rows, monetary=()):
    st.dataframe(rows, hide_index=True, width="stretch", column_config={
        column: st.column_config.NumberColumn(format="$%.2f") for column in monetary})

st.sidebar.title("KODF Finance")
st.sidebar.caption("Treasurer demonstration")
page = st.sidebar.radio("View", ["Overview", "Transactions", "Rentals", "Budget", "Reconciliation", "Connections"])
period = st.sidebar.selectbox("Reporting period", ["All sample months"] + MONTHS)
st.sidebar.caption("Financial filters apply to Overview, Transactions, and Budget. Rentals and Reconciliation have separate dates.")
st.sidebar.divider()
st.sidebar.caption("Sample records: June–September 2026")
st.sidebar.caption("All amounts and statuses are fictional.")

st.title("KODF Treasurer Dashboard")
st.caption("Financial visibility • rental collections • monthly close")
st.info("DEMO — fictional data. No bank, QuickBooks, Square, Stripe, or Acuity connection is active.")
selected = TRANSACTIONS if period == "All sample months" else [r for r in TRANSACTIONS if r["Date"].startswith(period)]
income = sum(r["Amount"] for r in selected if r["Type"] == "Income")
expense = sum(r["Amount"] for r in selected if r["Type"] == "Expense")

if page == "Overview":
    st.subheader(f"Financial overview · {period}")
    a, b, c = st.columns(3)
    a.metric("Income", money(income))
    b.metric("Expenses", money(expense))
    c.metric("Net income", money(income - expense))
    st.caption("Net income is income less expenses; it is not an available bank balance.")
    trend = [{"Month": m, "Income": sum(v[i] for v in INCOME.values()),
              "Expenses": sum(v[i] for v in EXPENSES.values())}
             for i, m in enumerate(MONTHS) if period == "All sample months" or m == period]
    st.subheader("Income and expenses")
    st.bar_chart(trend, x="Month", y=["Income", "Expenses"], stack=False,
                 color=["#A6192E", "#65758B"])
    left, right = st.columns(2)
    with left:
        st.subheader("Income by source")
        show_table([{"Source": k, "Income": sum(r["Amount"] for r in selected if r["Type"] == "Income" and r["Category"] == k)} for k in INCOME], ("Income",))
    with right:
        st.subheader("Next actions")
        st.write("• Review the September bank reconciliation status.")
        st.write("• Follow up on sample rental balances.")
        st.write("• Investigate expenses above the sample budget.")
        st.caption("These are demonstration prompts, not findings about KODF's actual finances.")

elif page == "Transactions":
    st.subheader("Sample monthly transaction summaries")
    kind = st.selectbox("Transaction type", ["All", "Income", "Expense"])
    categories = st.multiselect("Categories", list(INCOME) + list(EXPENSES))
    query = st.text_input("Search descriptions").strip().lower()
    rows = [r for r in selected if (kind == "All" or r["Type"] == kind)
            and (not categories or r["Category"] in categories)
            and query in r["Description"].lower()]
    if rows:
        show_table(rows, ("Amount",))
        st.caption(f"{len(rows)} sample summary rows. Expense amounts are displayed as positive values.")
        st.download_button("Download filtered sample CSV", csv_bytes(rows), "kodf_demo_transactions.csv", "text/csv")
    else:
        st.warning("No sample rows match those filters.")

elif page == "Rentals":
    st.subheader("Rental collections")
    as_of = st.date_input("Review as of", date(2026, 10, 1))
    rentals = [{"Booking": "DEMO-001", "Event date": date(2026, 10, 24), "Total": 475, "Paid": 200},
               {"Booking": "DEMO-002", "Event date": date(2026, 11, 7), "Total": 475, "Paid": 475},
               {"Booking": "DEMO-003", "Event date": date(2026, 11, 15), "Total": 450, "Paid": 200},
               {"Booking": "DEMO-004", "Event date": date(2026, 11, 19), "Total": 425, "Paid": 200}]
    for r in rentals:
        r["Balance"] = r["Total"] - r["Paid"]
        r["Balance due"] = r["Event date"] - timedelta(days=30)
        r["Status"] = "Paid" if not r["Balance"] else "Overdue" if r["Balance due"] < as_of else "Due today" if r["Balance due"] == as_of else "Upcoming"
    a, b = st.columns(2)
    a.metric("Outstanding sample balances", money(sum(r["Balance"] for r in rentals)))
    b.metric("Overdue sample balances", money(sum(r["Balance"] for r in rentals if r["Status"] == "Overdue")))
    show_table(rentals, ("Total", "Paid", "Balance"))
    st.caption("Sample rule: remaining balance due 30 days before the event. Rental balances are separate from the financial summary data.")

elif page == "Budget":
    st.subheader("Expense budget versus actual")
    count = len(MONTHS) if period == "All sample months" else 1
    rows = []
    for category, monthly in BUDGETS.items():
        actual = sum(r["Amount"] for r in selected if r["Type"] == "Expense" and r["Category"] == category)
        budget = monthly * count