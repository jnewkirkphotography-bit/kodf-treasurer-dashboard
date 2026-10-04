"""KODF Treasurer Dashboard — expanded fictional demonstration.

Replace streamlit_app.py in the existing project. Keep authentication secrets private.
All input changes are session-only. No production accounting, storage, email delivery,
or integration is implemented. Python stdlib + Streamlit (existing app dependency).
"""
import csv
import io
from datetime import date, timedelta
from urllib.parse import urlparse
import streamlit as st

MONTHS = ['2026-06', '2026-07', '2026-08', '2026-09']
INCOME = {'Rentals': [3400, 4100, 3650, 4550], 'Donations': [1250, 900, 1600, 1100], 'Grants': [0, 5000, 0, 2500], 'B2B': [450, 600, 500, 700]}
EXPENSES = {'Utilities': [650, 720, 810, 690], 'Maintenance': [400, 1200, 350, 650], 'Programs': [800, 950, 1100, 850], 'Administration': [300, 300, 325, 325], 'Processing fees': [100, 125, 115, 140]}
BUDGETS = {'Utilities': 750, 'Maintenance': 600, 'Programs': 1000, 'Administration': 350, 'Processing fees': 130}
INCOME_TARGETS = {'Rentals': 4000, 'Donations': 1200, 'Grants': 1875, 'B2B': 600}
PRIOR_INCOME = [4700, 5800, 6200, 6800]
PRIOR_EXPENSES = [2400, 2900, 2650, 2800]
SNAPSHOT = date(2026, 9, 30)
BANKS = [
    {'Account': 'Pinnacle — Housing (sample)', 'Purpose': 'Rental operations', 'Balance': 18400, 'Restricted': 0},
    {'Account': 'M&F — Beautillion (sample)', 'Purpose': 'Program funds', 'Balance': 6500, 'Restricted': 4500},
    {'Account': 'M&F — General Operating (sample)', 'Purpose': 'General operations', 'Balance': 14500, 'Restricted': 0},
]
GRANTS = [
    {'Grant': 'DEMO Youth Opportunity', 'Received': 5000, 'Spent': 2200, 'Committed': 1000, 'Permitted use': 'Youth program materials and delivery', 'Deadline': date(2026, 10, 15)},
    {'Grant': 'DEMO Community Skills', 'Received': 2500, 'Spent': 800, 'Committed': 500, 'Permitted use': 'Community skills workshops', 'Deadline': date(2026, 11, 15)},
]
STEPS = ['Obtain every bank statement', 'Match deposits, payments, and transfers', 'Review processor fees and refunds', 'Resolve exceptions and differences', 'Complete reconciliation in the accounting system', 'Obtain independent reviewer approval']
ISSUES = [
    {'ID': 'EX-001', 'Issue': 'Missing receipt', 'Item': 'Sample maintenance purchase', 'Amount': 125, 'Owner': 'Treasurer', 'Due': date(2026, 10, 2), 'Priority': 'High'},
    {'ID': 'EX-002', 'Issue': 'Uncategorized item', 'Item': 'Sample bank payment', 'Amount': 80, 'Owner': 'Assistant Treasurer', 'Due': date(2026, 10, 6), 'Priority': 'Medium'},
    {'ID': 'EX-003', 'Issue': 'Potential duplicate', 'Item': 'Two similar sample program entries; verify before removal', 'Amount': 150, 'Owner': 'Treasurer', 'Due': date(2026, 10, 7), 'Priority': 'Medium'},
]


def money(value):
    return f'${value:,.2f}'


def total(groups, indices):
    return sum(values[i] for values in groups.values() for i in indices)


def budget_rows(indices):
    return [{'Category': k, 'Budget': monthly * len(indices), 'Actual': sum(EXPENSES[k][i] for i in indices),
             'Remaining': monthly * len(indices) - sum(EXPENSES[k][i] for i in indices),
             'Status': 'Over budget' if sum(EXPENSES[k][i] for i in indices) > monthly * len(indices) else 'Within budget'} for k, monthly in BUDGETS.items()]


def rental_rows(as_of):
    bookings = [('DEMO-001', date(2026, 10, 24), 475, 200), ('DEMO-002', date(2026, 11, 7), 475, 475),
                ('DEMO-003', date(2026, 11, 15), 450, 200), ('DEMO-004', date(2026, 11, 19), 425, 200),
                ('DEMO-005', date(2026, 12, 12), 475, 0)]
    rows = []
    for booking, event, price, paid in bookings:
        due, balance = event - timedelta(days=30), price - paid
        status = 'Paid' if not balance else 'Overdue' if due < as_of else 'Due today' if due == as_of else 'Due within 7 days' if due <= as_of + timedelta(days=7) else 'Upcoming'
        rows.append({'Booking': booking, 'Event date': event, 'Total': price, 'Paid': paid, 'Deposit shortfall': max(0, 200 - paid), 'Balance': balance, 'Balance due': due, 'Status': status})
    return rows


def transaction_rows(indices):
    return [{'Date': f'{MONTHS[i]}-15', 'Type': kind, 'Category': k, 'Amount': values[i], 'Description': f'Sample monthly {k.lower()} total'}
            for kind, groups in [('Income', INCOME), ('Expense', EXPENSES)] for k, values in groups.items() for i in indices if values[i]]


def processor_rows(indices):
    # Illustrative subsets of income, not additional ledger entries. Gross includes refunds.
    rows = []
    for i in indices:
        for processor, gross, refunds, fees in [('Square', INCOME['Rentals'][i] + 50, 50, round(EXPENSES['Processing fees'][i] * .6, 2)),
                                               ('Stripe', INCOME['Donations'][i] + 25, 25, round(EXPENSES['Processing fees'][i] * .4, 2))]:
            rows.append({'Month': MONTHS[i], 'Processor': processor, 'Gross': gross, 'Refunds': refunds, 'Fees': fees, 'Expected net': gross - refunds - fees, 'Payout status': 'Sample matched' if i < 3 else 'Sample awaiting review'})
    return rows


def forecast_rows(start, months, opening, monthly_income, monthly_expense, growth):
    rows, balance = [], opening
    for i in range(months):
        absolute = start.year * 12 + start.month - 1 + i
        year, month_index = divmod(absolute, 12)
        inflow, outflow = round(monthly_income * (1 + growth / 100) ** i, 2), round(monthly_expense, 2)
        balance = round(balance + inflow - outflow, 2)
        rows.append({'Month': f'{year}-{month_index + 1:02d}', 'Forecast income': inflow, 'Forecast expenses': outflow, 'Net flow': inflow - outflow, 'Closing unrestricted cash': balance})
    return rows


def table(rows, monetary=()):
    if not rows:
        st.info('No items match this view.')
        return
    st.dataframe(rows, hide_index=True, width='stretch', column_config={k: st.column_config.NumberColumn(format='$%.2f') for k in monetary})


def csv_data(rows):
    if not rows:
        return ''
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def download(rows, name, label='Download fictional report CSV'):
    if rows:
        st.download_button(label, csv_data(rows), f'kodf_demo_{name}.csv', 'text/csv', key=f'download_{name}')


def go(page):
    st.session_state['dashboard_page'] = page


def close_rows(indices):
    # Practice checklist deliberately cannot approve a financial close.
    return [{'Month': MONTHS[i], 'Status': 'Sample approved' if i < 3 else 'Sample awaiting independent review', 'Accounts reconciled': '3 of 3' if i < 3 else '1 of 3', 'Reviewer': 'Sample independent reviewer' if i < 3 else 'Pending'} for i in indices]


def action_rows(as_of, indices):
    rows = []
    for r in rental_rows(as_of):
        if r['Status'] in {'Overdue', 'Due today', 'Due within 7 days'} or r['Deposit shortfall']:
            rows.append({'ID': r['Booking'], 'Priority': 'High' if r['Status'] == 'Overdue' else 'Medium', 'Area': 'Rentals', 'Action': 'Collect deposit' if r['Deposit shortfall'] else f"Follow up: {r['Status'].lower()}", 'Amount': r['Deposit shortfall'] or r['Balance'], 'Due': r['Balance due'], 'Owner': 'Housing / Finance', 'Page': 'Rentals'})
    for r in budget_rows(indices):
        if r['Remaining'] < 0:
            rows.append({'ID': f"BUD-{r['Category']}", 'Priority': 'Medium', 'Area': 'Budget', 'Action': f"Review {r['Category'].lower()} overspend", 'Amount': -r['Remaining'], 'Due': SNAPSHOT, 'Owner': 'Treasurer', 'Page': 'Budget'})
    for category, monthly_target in INCOME_TARGETS.items():
        shortfall = monthly_target * len(indices) - sum(INCOME[category][i] for i in indices)
        if shortfall > 0:
            rows.append({'ID': f'INC-{category}', 'Priority': 'Medium', 'Area': 'Income', 'Action': f'Review {category.lower()} income below target', 'Amount': shortfall, 'Due': SNAPSHOT, 'Owner': 'Treasurer / Committee', 'Page': 'Budget'})
    if 3 in indices:
        rows.append({'ID': 'CLOSE-09', 'Priority': 'High', 'Area': 'Close', 'Action': 'Resolve September reconciliation and obtain independent review', 'Amount': 50, 'Due': date(2026, 10, 10), 'Owner': 'Finance / Reviewer', 'Page': 'Reconciliation'})
    for r in ISSUES:
        if st.session_state.get(f"issue_status_{r['ID']}", 'Open') != 'Resolved':
            rows.append({'ID': r['ID'], 'Priority': r['Priority'], 'Area': 'Exceptions', 'Action': r['Issue'], 'Amount': r['Amount'], 'Due': r['Due'], 'Owner': r['Owner'], 'Page': 'Exceptions'})
    for g in GRANTS:
        if g['Deadline'] <= as_of + timedelta(days=30):
            rows.append({'ID': g['Grant'], 'Priority': 'High' if g['Deadline'] < as_of else 'Medium', 'Area': 'Grants', 'Action': 'Prepare grant report', 'Amount': 0, 'Due': g['Deadline'], 'Owner': 'Grant chair / Treasurer', 'Page': 'Funds & Grants'})
    return sorted(rows, key=lambda r: (r['Priority'] != 'High', r['Due']))


def summary_report(indices):
    return [{'Month': MONTHS[i], 'Income': total(INCOME, [i]), 'Expenses': total(EXPENSES, [i]), 'Net income': total(INCOME, [i]) - total(EXPENSES, [i]), 'Approval': 'Sample approved' if i < 3 else 'Sample preliminary'} for i in indices]


def main():
    st.set_page_config(page_title='KODF | Treasurer Dashboard', page_icon='📊', layout='wide')
    if not st.user.is_logged_in:
        st.title('KODF Treasurer Dashboard')
        st.write('Sign in with your approved KODF Google account.')
        st.button('Sign in with Google', on_click=st.login)
        st.stop()
    access = st.secrets.get('access', {})
    def emails(key):
        return {str(e).strip().lower() for e in access.get(key, [])}
    user_email = str(st.user.get('email', '')).strip().lower()
    if st.user.get('email_verified', False) is not True or user_email not in emails('allowed_emails'):
        st.error('You do not have access to this dashboard.')
        st.button('Sign out', on_click=st.logout)
        st.stop()
    role = 'Administrator' if user_email in emails('admin_emails') else 'Finance' if user_email in emails('finance_emails') else 'Viewer'
    can_manage = role in {'Administrator', 'Finance'}
    pages = ['Overview', 'Budget', 'Close Summary']
    if can_manage:
        pages += ['Action Required', 'Accounts & Cash', 'History', 'Forecast', 'Transactions', 'Rentals', 'Processing', 'Funds & Grants', 'Reconciliation', 'Exceptions', 'Documents', 'Report Center']
    if role == 'Administrator':
        pages += ['Connections']
    st.sidebar.title('KODF Finance')
    st.sidebar.caption(f'Access: {role}')
    st.sidebar.caption(f'Signed in as: {user_email}')
    st.sidebar.button('Sign out', on_click=st.logout)
    if st.session_state.get('dashboard_page') not in pages:
        st.session_state['dashboard_page'] = 'Overview'
    page = st.sidebar.radio('View', pages, key='dashboard_page')
    period = st.sidebar.selectbox('Reporting period', ['All sample months'] + MONTHS)
    as_of = st.sidebar.date_input('Action review date', date(2026, 10, 3))
    st.sidebar.caption('Reporting period filters financial reports. Cash is a September 30 snapshot; rentals and tasks use the action review date.')
    indices = [i for i, m in enumerate(MONTHS) if period == 'All sample months' or m == period]
    if page not in pages:
        st.error('You do not have access to this report.')
        st.stop()
    income, expense = total(INCOME, indices), total(EXPENSES, indices)
    actions = action_rows(as_of, indices) if can_manage else []
    st.title('KODF Treasurer Dashboard')
    st.caption('Financial visibility · cash planning · collections · monthly close')
    st.info('DEMO — fictional data only. No banks or accounting systems are connected. Practice changes are temporary and are not shared or saved permanently.')
    st.caption('Sample data as of September 30, 2026 · Live refresh: none · September: preliminary · June–August: fictional approved examples')
    if can_manage:
        st.button(f'Action Required ({len(actions)})', type='primary', on_click=go, args=('Action Required',))
    else:
        st.caption('Board view: summaries only. Ask Finance about unresolved items or preliminary figures.')

    if page == 'Overview':
        st.subheader(f'Financial overview · {period}')
        a, b, c = st.columns(3)
        a.metric('Income', money(income))
        b.metric('Expenses', money(expense))
        c.metric('Net income', money(income - expense))
        st.caption('Net income is income less expenses; it is not a bank balance or unrestricted cash.')
        st.bar_chart(summary_report(indices), x='Month', y=['Income', 'Expenses'], stack=False)
        left, right = st.columns(2)
        with left:
            st.subheader('Income by source')
            table([{'Source': k, 'Income': sum(v[i] for i in indices)} for k, v in INCOME.items()], ['Income'])
        with right:
            st.subheader('Close status')
            table(close_rows(indices))
        if can_manage:
            st.subheader('Next actions')
            table([{k: r[k] for k in ['Priority', 'Area', 'Action', 'Owner']} for r in actions[:5]])
        with st.expander('Board report summaries'):
            st.write('Approved examples exclude September until Finance completes independent review.')
            table(summary_report([i for i in indices if i < 3]), ['Income', 'Expenses', 'Net income'])
            if 3 in indices:
                st.warning('September is preliminary and is excluded from the approved board report.')

    elif page == 'Budget':
        st.subheader('Budget versus actual')
        rows = budget_rows(indices)
        table(rows, ['Budget', 'Actual', 'Remaining'])
        st.bar_chart(rows, x='Category', y=['Budget', 'Actual'], stack=False)
        st.subheader('Income targets')
        table([{'Source': k, 'Target': v * len(indices), 'Actual': sum(INCOME[k][i] for i in indices), 'Variance': sum(INCOME[k][i] for i in indices) - v * len(indices)} for k, v in INCOME_TARGETS.items()], ['Target', 'Actual', 'Variance'])
        st.caption('Expense Remaining below zero means overspending. Income Variance below zero means income below target. Grant targets do not establish timing or availability.')
        if can_manage:
            download(rows, 'budget')

    elif page == 'Close Summary':
        st.subheader('Monthly close summary')
        table(close_rows(indices))
        st.caption('These are seeded fictional statuses. Practice checklist changes cannot approve a close or alter this report.')

    elif page == 'Action Required' and can_manage:
        st.subheader('Items needing attention')
        st.caption('This queue combines budget alerts for the reporting period with rental, exception, and grant tasks for the action review date. Amounts are different types of exposure and should not be added together.')
        area = st.selectbox('Area', ['All'] + sorted({r['Area'] for r in actions}))
        priority = st.selectbox('Priority', ['All', 'High', 'Medium'])
        filtered = [r for r in actions if (area == 'All' or r['Area'] == area) and (priority == 'All' or r['Priority'] == priority)]
        table([{k: v for k, v in r.items() if k != 'Page'} for r in filtered], ['Amount'])
        if filtered:
            chosen = st.selectbox('Choose an item to investigate', [r['ID'] for r in filtered])
            selected = next(r for r in filtered if r['ID'] == chosen)
            st.button(f"Open {selected['Page']}", on_click=go, args=(selected['Page'],))
        download(filtered, 'actions')

    elif page == 'Accounts & Cash' and can_manage:
        st.subheader('Bank accounts and available cash')
        balance, restricted = sum(r['Balance'] for r in BANKS), sum(r['Restricted'] for r in BANKS)
        a, b, c = st.columns(3)
        a.metric('Sample total bank cash', money(balance))
        b.metric('Restricted cash', money(restricted))
        c.metric('Unrestricted cash', money(balance - restricted))
        table(BANKS, ['Balance', 'Restricted'])
        reserve = st.number_input('Planning reserve to retain', min_value=0.0, value=5000.0, step=500.0)
        st.metric('Unrestricted cash after planning reserve', money(balance - restricted - reserve))
        st.caption('September 30 snapshot. Opening sample cash of $20,000 plus $19,400 sample net income equals $39,400. Restricted balances total $4,500. Available cash here does not deduct unrecorded liabilities; the reserve is a planning assumption.')
        download(BANKS, 'cash_snapshot')

    elif page == 'History' and can_manage:
        st.subheader('Historical comparisons')
        rows = []
        for i in indices:
            current_i, current_e = total(INCOME, [i]), total(EXPENSES, [i])
            rows.append({'Month': MONTHS[i], '2025 income': PRIOR_INCOME[i], '2026 income': current_i, 'Income change': current_i - PRIOR_INCOME[i], '2025 expenses': PRIOR_EXPENSES[i], '2026 expenses': current_e})
        table(rows, ['2025 income', '2026 income', 'Income change', '2025 expenses', '2026 expenses'])
        st.bar_chart(rows, x='Month', y=['2025 income', '2026 income'], stack=False)
        if len(indices) == 1:
            i = indices[0]
            if i:
                st.metric('Income change from previous month', money(total(INCOME, [i]) - total(INCOME, [i - 1])))
            else:
                st.caption('Previous-month data is not provided for June.')
        st.caption('2025 values are fictional comparative monthly summaries, not imported transactions. Pre-cutover history can be added separately without duplicating current bookkeeping.')
        download(rows, 'historical_comparison')

    elif page == 'Forecast' and can_manage:
        st.subheader('Cash-flow scenario planner')
        st.warning('Forecasts are assumptions, not approved actual results. Defaults use unrestricted sample cash and recurring income; grants are excluded unless you deliberately include eligible unrestricted receipts.')
        months = st.slider('Forecast months', 1, 12, 6)
        opening = st.number_input('Opening unrestricted cash', min_value=0.0, value=34900.0, step=500.0)
        monthly_income = st.number_input('Expected monthly unrestricted collections', min_value=0.0, value=float(sum(sum(v) for k, v in INCOME.items() if k != 'Grants') / len(MONTHS)), step=100.0)
        monthly_expense = st.number_input('Expected monthly cash expenses', min_value=0.0, value=2725.0, step=100.0)
        growth = st.slider('Monthly collection growth (%)', -25, 25, 0)
        reserve = st.number_input('Minimum cash reserve', min_value=0.0, value=5000.0, step=500.0)
        rows = forecast_rows(date(2026, 10, 1), months, opening, monthly_income, monthly_expense, growth)
        table(rows, ['Forecast income', 'Forecast expenses', 'Net flow', 'Closing unrestricted cash'])
        st.line_chart(rows, x='Month', y='Closing unrestricted cash')
        if any(r['Closing unrestricted cash'] < reserve for r in rows):
            st.error('This scenario falls below your minimum reserve. Review collection timing, expenses, and commitments.')
        else:
            st.success('This fictional scenario remains above the selected reserve.')
        st.caption('Starts October 2026. Include rental receipts only once in the collection assumption. No automatic link to the separate rental schedule or liabilities is active.')
        download(rows, 'forecast')

    elif page == 'Transactions' and can_manage:
        st.subheader('Monthly transaction summaries')
        kind = st.selectbox('Type', ['All', 'Income', 'Expense'])
        categories = st.multiselect('Categories', list(INCOME) + list(EXPENSES))
        query = st.text_input('Search description').strip().lower()
        rows = [r for r in transaction_rows(indices) if (kind == 'All' or r['Type'] == kind) and (not categories or r['Category'] in categories) and query in r['Description'].lower()]
        table(rows, ['Amount'])
        st.caption('Aggregated fictional monthly rows, not individual bank transactions. Expense values are positive.')
        download(rows, 'transactions')

    elif page == 'Rentals' and can_manage:
        st.subheader('Rental collections and deadlines')
        rows = rental_rows(as_of)
        a, b, c = st.columns(3)
        a.metric('Outstanding balances', money(sum(r['Balance'] for r in rows)))
        b.metric('Overdue balances', money(sum(r['Balance'] for r in rows if r['Status'] == 'Overdue')))
        c.metric('Deposit shortfalls', money(sum(r['Deposit shortfall'] for r in rows)))
        status = st.selectbox('Rental status', ['All', 'Overdue', 'Due today', 'Due within 7 days', 'Upcoming', 'Paid'])
        table([r for r in rows if status == 'All' or r['Status'] == status], ['Total', 'Paid', 'Deposit shortfall', 'Balance'])
        st.caption('Sample deposit: $200; remaining balance due 30 days before event. Deposit shortfalls are included in outstanding balances. These future sample bookings are separate from June–September actual examples.')
        download(rows, 'rental_collections')

    elif page == 'Processing' and can_manage:
        st.subheader('Payment processing and payout review')
        rows = processor_rows(indices)
        table(rows, ['Gross', 'Refunds', 'Fees', 'Expected net'])
        st.caption('Expected net = gross less refunds and fees. Square represents rental income; Stripe represents donation income. Net collections before fees equal the corresponding Overview income. Fees equal the Overview processing-fee expense. These are supporting breakdowns, not additional income or expense.')
        st.warning('Sample payout labels are illustrative. Settlement timing, bank matching, and negative processor balances need live transaction data.')
        download(rows, 'processing')

    elif page == 'Funds & Grants' and can_manage:
        st.subheader('Restricted funds and grant reporting')
        rows = [{**g, 'Remaining': g['Received'] - g['Spent'], 'Uncommitted': g['Received'] - g['Spent'] - g['Committed']} for g in GRANTS]
        table(rows, ['Received', 'Spent', 'Committed', 'Remaining', 'Uncommitted'])
        st.caption('Sample grant receipts of $7,500 are already included in Overview grants. $3,000 sample spending is included within program expenses; do not add it again. Remaining $4,500 matches restricted bank cash. Commitments are illustrative future spending, not additional recorded expenses.')
        st.write('Finance and grant owners must confirm award restrictions, allowable costs, and reporting requirements before approving expenditures.')
        download(rows, 'grants')

    elif page == 'Reconciliation' and can_manage:
        st.subheader('Monthly reconciliation and independent review')
        month = st.selectbox('Close month', MONTHS, index=3)
        rows = []
        for i, account in enumerate(BANKS):
            rows.append({'Account': account['Account'], 'Month': month, 'Status': 'Sample reconciled' if month != MONTHS[-1] or i == 0 else 'Sample in review' if i == 1 else 'Sample awaiting statement', 'Unresolved difference': 50 if month == MONTHS[-1] and i == 1 else 0, 'Owner': 'Assistant Treasurer' if i == 1 else 'Treasurer'})
        table(rows, ['Unresolved difference'])
        st.warning('Practice checklist only. It does not reconcile bank accounts, approve a close, or change the Close Summary.')
        completed = [st.checkbox(task, key=f'close_{month}_{i}') for i, task in enumerate(STEPS)]
        st.progress(sum(completed) / len(STEPS))
        st.write(f'{sum(completed)} of {len(STEPS)} practice steps complete.')
        note_key = f'close_note_{month}'
        st.text_area('Practice close notes', key=note_key)
        download([{'Month': month, 'Task': task, 'Practice checked': completed[i], 'Practice notes': st.session_state.get(note_key, '')} for i, task in enumerate(STEPS)], 'practice_close')

    elif page == 'Exceptions' and can_manage:
        st.subheader('Financial exception review')
        st.caption('Changes are session-only; marking an item resolved removes its practice task from Action Required. It does not change bookkeeping or create an audit record.')
        for issue in ISSUES:
            with st.expander(f"{issue['ID']} · {issue['Issue']} · {money(issue['Amount'])}"):
                st.write(issue['Item'])
                st.caption(f"Owner: {issue['Owner']} · Due: {issue['Due']}")
                st.selectbox('Practice status', ['Open', 'In review', 'Resolved'], key=f"issue_status_{issue['ID']}")
                st.text_area('Practice resolution notes', key=f"issue_note_{issue['ID']}")
        download([{**r, 'Practice status': st.session_state.get(f"issue_status_{r['ID']}", 'Open'), 'Practice notes': st.session_state.get(f"issue_note_{r['ID']}", '')} for r in ISSUES], 'exceptions')

    elif page == 'Documents' and can_manage:
        st.subheader('Supporting documents')
        table([{'Document': 'Bank statements', 'Owner': 'Treasurer', 'Review': 'Each monthly close'}, {'Document': 'Receipts and invoices', 'Owner': 'Finance / purchasing owner', 'Review': 'Before expense approval'}, {'Document': 'Rental contracts', 'Owner': 'Housing committee', 'Review': 'Each booking'}, {'Document': 'Grant award letters', 'Owner': 'Grant chair', 'Review': 'Before spending'}, {'Document': 'Approved financial reports', 'Owner': 'Treasurer / reviewer', 'Review': 'After monthly close'}])
        links = st.secrets.get('documents', {})
        if links:
            for name, url in links.items():
                if isinstance(url, str) and urlparse(url).scheme == 'https' and urlparse(url).netloc:
                    st.link_button(str(name).replace('_', ' ').title(), url)
        else:
            st.info('No document folders configured. IT can add approved HTTPS folder links under [documents] in the live app Secrets.')
        st.caption('Finance-only links. Google Drive permissions must separately restrict the folders. This dashboard does not grant Drive access or prevent forwarding.')

    elif page == 'Report Center' and can_manage:
        st.subheader('Reports by audience')
        audience = st.selectbox('Report audience', ['Finance team', 'Board — approved summaries'])
        if audience == 'Board — approved summaries':
            rows = summary_report([i for i in indices if i < 3])
            table(rows, ['Income', 'Expenses', 'Net income'])
            if 3 in indices:
                st.warning('September is excluded because its fictional close is awaiting review.')
            download(rows, 'board_approved_summary')
        else:
            report = st.selectbox('Finance report', ['Monthly financial summary', 'Budget versus actual', 'Rental balances', 'Action queue', 'Processing breakdown', 'Grant balances'])
            datasets = {'Monthly financial summary': (summary_report(indices), ['Income', 'Expenses', 'Net income']), 'Budget versus actual': (budget_rows(indices), ['Budget', 'Actual', 'Remaining']), 'Rental balances': (rental_rows(as_of), ['Balance', 'Paid', 'Total']), 'Action queue': (actions, ['Amount']), 'Processing breakdown': (processor_rows(indices), ['Gross', 'Refunds', 'Fees', 'Expected net']), 'Grant balances': ([{**g, 'Remaining': g['Received'] - g['Spent']} for g in GRANTS], ['Received', 'Spent', 'Committed', 'Remaining'])}
            rows, monetary = datasets[report]
            table(rows, monetary)
            download(rows, 'finance_report')
        st.divider()
        st.write('Planned delivery: weekly finance notifications; monthly board summaries after independent approval. Officer reports require an approved scope and recipient list.')
        st.caption('No email automation is active. Downloads contain fictional data. Production delivery needs an approved recipient list, scheduler, freshness checks, finance approval, and delivery logs.')

    elif page == 'Connections' and role == 'Administrator':
        st.subheader('Connection status and implementation roadmap')
        table([{'System': system, 'Status': 'Not connected', 'Next step': task} for system, task in [('QuickBooks', 'Activate approved subscription; validate one month'), ('Banks', 'Connect to QuickBooks through authorized bank user'), ('Square / Stripe', 'Validate fees, refunds, transfers, and settlement mapping'), ('Acuity', 'Match booking and payment IDs'), ('Google Drive', 'Configure restricted document folders'), ('Database', 'Add shared durable tasks, approval records, and audit history'), ('Scheduled reports', 'Configure reviewed recipients and approved report delivery')]])
        st.caption('This screen does not collect credentials or activate integrations. Google authentication is already handled separately through existing [auth] settings.')
        with st.expander('Access diagnostics'):
            st.write(f"Admin role configured: {'admin_emails' in access}")
            st.write(f"Email matches admin list: {user_email in emails('admin_emails')}")
    st.divider()
    st.caption('KODF · Expanded Treasurer Dashboard · Fictional demonstration. Finance owns categorization, reconciliation, and financial approval; IT maintains the technology.')


if __name__ == '__main__':
    main()
