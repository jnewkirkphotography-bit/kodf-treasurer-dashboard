"""KODF dashboard: fictional data, Google authentication, and restricted roles."""
import csv
import io
from datetime import date, timedelta
import streamlit as st

st.set_page_config(page_title="KODF | Treasurer Dashboard", page_icon="📊", layout="wide")
if not st.user.is_logged_in:
    st.title("KODF Treasurer Dashboard")
    st.write("Sign in with your approved KODF Google account.")
    st.button("Sign in with Google", on_click=st.login)
    st.stop()

access = st.secrets.get("access", {})
def emails(key):
    return {str(e).strip().lower() for e in access.get(key, [])}

user_email = str(st.user.get("email", "")).strip().lower()
if st.user.get("email_verified", False) is not True or user_email not in emails("allowed_emails"):
    st.error("You do not have access to this dashboard.")
    st.button("Sign out", on_click=st.logout)
    st.stop()

# Role membership alone never grants admission; allowed_emails is also required.
role = "Administrator" if user_email in emails("admin_emails") else "Finance" if user_email in emails("finance_emails") else "Viewer"
can_manage = role in {"Administrator", "Finance"}
pages = ["Overview", "Budget", "Close Summary"]
if can_manage:
    pages += ["Transactions", "Rentals", "Reconciliation", "Connections"]
st.sidebar.title("KODF Finance")
st.sidebar.caption(f"Signed in as: {user_email}")
st.sidebar.caption(f"Admin role configured: {'admin_emails' in access}")
st.sidebar.caption(f"Email matches admin list: {user_email in emails('admin_emails')}")
st.sidebar.button("Sign out", on_click=st.logout)
# Clear a previously selected restricted page if this session's role changes.
if st.session_state.get("dashboard_page") not in pages:
    st.session_state["dashboard_page"] = "Overview"
page = st.sidebar.radio("View", pages, key="dashboard_page")
if page not in pages:
    st.error("You do not have access to this report.")
    st.stop()

MONTHS = ["2026-06", "2026-07", "2026-08", "2026-09"]
INCOME = {"Rentals": [3400,4100,3650,4550], "Donations": [1250,900,1600,1100], "Grants": [0,5000,0,2500], "B2B": [450,600,500,700]}
EXPENSES = {"Utilities": [650,720,810,690], "Maintenance": [400,1200,350,650], "Programs": [800,950,1100,850], "Administration": [300,300,325,325], "Processing fees": [100,125,115,140]}
BUDGETS = {"Utilities":750, "Maintenance":600, "Programs":1000, "Administration":350, "Processing fees":130}
period = st.sidebar.selectbox("Reporting period", ["All sample months"] + MONTHS)
indices = [i for i,m in enumerate(MONTHS) if period == "All sample months" or m == period]
def money(value):
    return f"${value:,.2f}"
def table(rows, monetary=()):
    st.dataframe(rows, hide_index=True, width="stretch", column_config={k:st.column_config.NumberColumn(format="$%.2f") for k in monetary})

st.title("KODF Treasurer Dashboard")
st.info("DEMO — all data is fictional. No bank or accounting connection is active. Changes are not saved permanently.")
income = sum(v[i] for v in INCOME.values() for i in indices)
expense = sum(v[i] for v in EXPENSES.values() for i in indices)

if page == "Overview":
    st.subheader(f"Financial overview · {period}")
    a,b,c = st.columns(3)
    a.metric("Income", money(income))
    b.metric("Expenses", money(expense))
    c.metric("Net income", money(income-expense))
    st.caption("Net income is income less expenses, not an available bank balance. Bank balances are not available in this demo.")
    st.bar_chart([{"Month":MONTHS[i], "Income":sum(v[i] for v in INCOME.values()), "Expenses":sum(v[i] for v in EXPENSES.values())} for i in indices], x="Month", y=["Income","Expenses"], stack=False)
    st.subheader("Income by source")
    table([{"Source":k,"Income":sum(v[i] for i in indices)} for k,v in INCOME.items()], ["Income"])

elif page == "Budget":
    st.subheader("Expense budget versus actual")
    rows = []
    for category,monthly in BUDGETS.items():
        actual = sum(EXPENSES[category][i] for i in indices)
        budget = monthly * len(indices)
        rows.append({"Category":category,"Budget":budget,"Actual":actual,"Remaining":budget-actual})
    table(rows,["Budget","Actual","Remaining"])
    st.caption("Negative remaining amounts indicate expenses above the fictional budget.")

elif page == "Close Summary":
    st.subheader("Monthly close summary")
    table([{"Month":MONTHS[i],"Status":"Sample: complete" if i < 3 else "Sample: awaiting review"} for i in indices])
    st.caption("These fictional statuses are separate from the interactive reconciliation demonstration. No actual reconciliation has been completed.")

elif page == "Transactions" and can_manage:
    st.subheader("Sample monthly transaction summaries")
    kind = st.selectbox("Transaction type",["All","Income","Expense"])
    rows = [{"Date":f"{MONTHS[i]}-15","Type":t,"Category":k,"Amount":v[i],"Description":f"Sample monthly {k.lower()} total"} for t,groups in [("Income",INCOME),("Expense",EXPENSES)] for k,v in groups.items() for i in indices if v[i] and kind in ["All",t]]
    table(rows,["Amount"])
    if rows:
        buf = io.StringIO()
        writer = csv.DictWriter(buf,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        st.download_button("Download sample CSV",buf.getvalue(),"kodf_demo_transactions.csv","text/csv")

elif page == "Rentals" and can_manage:
    st.subheader("Rental collections")
    as_of = st.date_input("Review as of",date(2026,10,1))
    rows = []
    for booking,event,total,paid in [("DEMO-001",date(2026,10,24),475,200),("DEMO-002",date(2026,11,7),475,475),("DEMO-003",date(2026,11,15),450,200),("DEMO-004",date(2026,11,19),425,200)]:
        balance = total-paid
        due = event-timedelta(days=30)
        rows.append({"Booking":booking,"Event date":event,"Total":total,"Paid":paid,"Balance":balance,"Balance due":due,"Status":"Paid" if not balance else "Overdue" if due < as_of else "Due today" if due == as_of else "Upcoming"})
    st.metric("Outstanding sample balances",money(sum(r["Balance"] for r in rows)))
    table(rows,["Total","Paid","Balance"])
    st.caption("Remaining balances are due 30 days before the event. These sample rentals are separate from the financial overview.")

elif page == "Reconciliation" and can_manage:
    st.subheader("Monthly reconciliation demonstration")
    month = st.selectbox("Close month",MONTHS)
    st.warning("Checklist changes apply only to this session. They do not save an official close or change the Close Summary.")
    steps = ["Obtain statements for every bank account","Match deposits and payments to accounting records","Review Square and Stripe payouts and fees","Investigate outstanding items and differences","Have a second authorized person review the close"]
    complete = [st.checkbox(step,key=f"close_{month}_{i}") for i,step in enumerate(steps)]
    st.write(f"{sum(complete)} of {len(steps)} demonstration steps checked.")

elif page == "Connections" and can_manage:
    st.subheader("Financial connections")
    table([{"System":name,"Status":"Not connected"} for name in ["Banks","QuickBooks","Square","Stripe","Acuity"]])
    st.caption("This page shows connection status only. No credentials are collected and no connection can be activated in this demo.")
