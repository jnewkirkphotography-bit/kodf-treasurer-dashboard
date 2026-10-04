"""KODF Treasurer Dashboard — expanded fictional demonstration.

Replace streamlit_app.py in the existing project. Keep authentication secrets private.
Practice changes and CSV imports are session-only; audit events, warrants, and receipts use external PostgreSQL.
No live accounting integration or email delivery is implemented.
Dependencies: Streamlit, psycopg[binary]>=3.3,<4, and Pillow>=12.3,<13. Configure [audit] in live Secrets.
"""
import csv
import io
from datetime import date, timedelta
from urllib.parse import urlparse
import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from zoneinfo import ZoneInfo

AUDIT_SETUP_SQL = '''-- Run once as database owner. Keep owner credentials out of Streamlit.
CREATE SCHEMA IF NOT EXISTS kodf;
REVOKE ALL ON SCHEMA kodf FROM PUBLIC;
CREATE TABLE IF NOT EXISTS kodf.audit_events (
    id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_email text NOT NULL,
    actor_subject text NOT NULL,
    actor_role text NOT NULL,
    session_id uuid NOT NULL,
    event_type text NOT NULL,
    target text NOT NULL,
    result text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_time_idx ON kodf.audit_events(occurred_at DESC);
REVOKE ALL ON kodf.audit_events FROM PUBLIC;
-- Provision separate LOGIN users securely using your database provider:
-- kodf_audit_writer and kodf_audit_reader. Do not use a database owner login.
GRANT USAGE ON SCHEMA kodf TO kodf_audit_writer, kodf_audit_reader;
REVOKE ALL ON kodf.audit_events FROM kodf_audit_writer, kodf_audit_reader;
GRANT INSERT ON kodf.audit_events TO kodf_audit_writer;
GRANT SELECT ON kodf.audit_events TO kodf_audit_reader;
-- Neither role gets UPDATE, DELETE, TRUNCATE, CREATE or ownership rights.
'''


def current_identity():
    access = st.secrets.get('access', {})
    email = str(st.user.get('email', '')).strip().lower()
    approved = {str(e).strip().lower() for e in access.get('allowed_emails', [])}
    verified = st.user.is_logged_in and st.user.get('email_verified', False) is True
    role = 'Denied'
    if verified and email in approved:
        role = 'Administrator' if email in {str(e).strip().lower() for e in access.get('admin_emails', [])} else 'Finance' if email in {str(e).strip().lower() for e in access.get('finance_emails', [])} else 'Member' if email in {str(e).strip().lower() for e in access.get('member_emails', [])} else 'Viewer'
    return email, role, str(st.user.get('sub', ''))[:255]


def file_permission(kind):
    email, role, _ = current_identity()
    if role == 'Administrator':
        return True
    if role != 'Finance':
        return False
    access = st.secrets.get('access', {})
    key = 'export_emails' if kind == 'export' else 'import_emails'
    # No implicit Finance file permissions: use explicit allowlists.
    return email in {str(e).strip().lower() for e in access.get(key, [])}


def audit_connection(reader=False):
    import psycopg
    config = st.secrets.get('audit', {})
    key = 'read_database_url' if reader else 'write_database_url'
    dsn = str(config.get(key, ''))
    if not dsn:
        raise RuntimeError('Audit database is not configured')
    # Verify database hostname and public CA certificate; never disable TLS verification.
    return psycopg.connect(dsn, sslmode='verify-full', sslrootcert='system', connect_timeout=5,
                           options='-c statement_timeout=5000')


def audit_event(event_type, target, result='success', metadata=None, event_id=None):
    email, role, subject = current_identity()
    session = st.session_state.setdefault('audit_session_id', str(uuid.uuid4()))
    allowed = {'period', 'row_count', 'format', 'sha256', 'size_bytes', 'filename', 'reason', 'item_id', 'old_status', 'new_status', 'note_length', 'report', 'review_date'}
    clean = {k: v for k, v in (metadata or {}).items() if k in allowed}
    identifier = event_id or str(uuid.uuid4())
    try:
        with audit_connection() as conn:
            conn.execute('''INSERT INTO kodf.audit_events
                (id, actor_email, actor_subject, actor_role, session_id, event_type, target, result, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)''',
                (identifier, email[:255], subject, role, session, event_type[:80], str(target)[:255], result[:40], json.dumps(clean, default=str)))
        return True
    except Exception:
        # Never expose connection strings, credentials, SQL details or file contents.
        st.session_state['audit_write_failed'] = True
        return False


def log_download(name, metadata):
    if not file_permission('export'):
        audit_event('download_denied', name, 'denied', {'reason': 'permission'})
        return
    if not audit_event('download_requested', name, metadata=metadata):
        st.session_state['audit_notice'] = 'A download request could not be recorded. Further export preparation is blocked until audit logging recovers.'


def safe_csv_value(value):
    # Neutralize spreadsheet formula injection in exported text; preserve numbers.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def audit_logout():
    audit_event('dashboard_sign_out_requested', 'dashboard')
    st.logout()


def record_practice_change(key, item_id):
    value = st.session_state.get(key)
    previous = st.session_state.get('audit_previous_' + key)
    if value != previous:
        # Log status/count only. Do not copy free-form finance notes into the audit log.
        metadata = {'item_id': item_id}
        if 'note' in key:
            metadata['note_length'] = len(str(value or ''))
        else:
            metadata.update(old_status=previous, new_status=value)
        if audit_event('practice_change', item_id, metadata=metadata):
            st.session_state['audit_previous_' + key] = value


def validate_import(data):
    if len(data) > 1024 * 1024:
        raise ValueError('File exceeds the 1 MB limit.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Use a UTF-8 CSV file.') from None
    reader = csv.DictReader(io.StringIO(text))
    fields = ['Date', 'Type', 'Category', 'Amount', 'Description']
    if reader.fieldnames != fields:
        raise ValueError('Columns must be Date,Type,Category,Amount,Description in that order.')
    rows = []
    for line, row in enumerate(reader, 2):
        if len(rows) >= 1000:
            raise ValueError('File exceeds the 1,000 row limit.')
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f'Row {line}: incorrect column count.')
        try:
            parsed_date = date.fromisoformat(row['Date'])
            amount = Decimal(row['Amount'])
        except (ValueError, InvalidOperation):
            raise ValueError(f'Row {line}: invalid date or amount.') from None
        if not amount.is_finite() or amount < 0 or amount > 10000000 or amount != amount.quantize(Decimal('.01')):
            raise ValueError(f'Row {line}: amount must be nonnegative, at most 10 million, with at most two decimal places.')
        kind = row['Type']
        categories = INCOME if kind == 'Income' else EXPENSES if kind == 'Expense' else {}
        if row['Category'] not in categories:
            raise ValueError(f'Row {line}: invalid type or category.')
        if len(row['Description']) > 200 or any(ord(c) < 32 for c in row['Description']):
            raise ValueError(f'Row {line}: description exceeds 200 characters or contains control characters.')
        rows.append({'Date': parsed_date.isoformat(), 'Type': kind, 'Category': row['Category'], 'Amount': float(amount), 'Description': row['Description']})
    if not rows:
        raise ValueError('File contains no data rows.')
    return rows


def import_page():
    st.subheader('CSV import practice')
    st.warning('Fictional files only. Imports go into a temporary practice batch, not QuickBooks, bank records, or the dashboard financial totals. The audit event is permanent when the database is connected; imported contents are not retained after this session.')
    if not file_permission('import'):
        st.info('CSV imports require an Administrator account or explicit import permission.')
        return
    if not st.session_state.get('audit_ready', False):
        st.warning('Uploads are blocked until audit logging is configured and healthy.')
        return
    st.code('Date,Type,Category,Amount,Description\n2026-09-15,Income,Rentals,475.00,Fictional rental')
    uploaded = st.file_uploader('Upload a fictional CSV (maximum 1 MB / 1,000 rows)', type=['csv'], key='practice_upload')
    if uploaded is not None:
        data = uploaded.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        filename = PurePath(uploaded.name.replace('\\', '/')).name[:120]
        meta = {'filename': filename, 'size_bytes': len(data), 'sha256': digest}
        token = (digest, filename)
        if st.session_state.get('audit_upload_token') != token:
            if not audit_event('file_uploaded', 'practice_csv', metadata=meta):
                st.error('Upload could not be logged. Import is blocked.')
                return
            st.session_state['audit_upload_token'] = token
        try:
            rows = validate_import(data)
        except (ValueError, csv.Error) as exc:
            if st.session_state.get('audit_validation_token') != token:
                audit_event('import_validation', 'practice_csv', 'rejected', {**meta, 'reason': 'invalid_csv'})
                st.session_state['audit_validation_token'] = token
            st.error(str(exc))
            return
        if st.session_state.get('audit_validation_token') != token:
            if not audit_event('import_validation', 'practice_csv', 'accepted', {**meta, 'row_count': len(rows)}):
                st.error('Validation could not be logged. Import is blocked.')
                return
            st.session_state['audit_validation_token'] = token
        table(rows, ['Amount'])
        if st.button('Import into temporary practice batch', disabled=st.session_state.get('audit_imported_token') == token):
            # Durable event records the practice operation, not a production DB commit.
            if not audit_event('practice_import_accepted', 'practice_csv', metadata={**meta, 'row_count': len(rows)}):
                st.error('Import could not be logged. No practice batch was changed.')
                return
            st.session_state['practice_import_rows'] = rows
            st.session_state['audit_imported_token'] = token
            st.success(f'{len(rows)} rows imported into this session’s practice batch. Financial totals are unchanged.')
    if st.session_state.get('practice_import_rows'):
        st.caption(f"Current temporary batch: {len(st.session_state['practice_import_rows'])} rows.")


def audit_page():
    st.subheader('Security activity log')
    st.caption('Administrator-only. Timestamps are stored by PostgreSQL in UTC and displayed in Eastern time. Session started means dashboard access, not proof of a fresh Google MFA challenge.')
    if current_identity()[1] != 'Administrator':
        st.stop()
    start = st.date_input('From', date.today() - timedelta(days=7), key='audit_from')
    end = st.date_input('Through', date.today(), key='audit_through')
    user = st.text_input('Exact user email (optional)').strip().lower()
    event = st.text_input('Exact event type (optional)').strip()
    if start > end:
        st.error('From must be before Through.')
    else:
        try:
            from datetime import datetime, time
            from psycopg.rows import dict_row
            eastern = ZoneInfo('America/New_York')
            lower = datetime.combine(start, time.min, eastern)
            upper = datetime.combine(end + timedelta(days=1), time.min, eastern)
            with audit_connection(reader=True) as conn:
                with conn.cursor(row_factory=dict_row) as cursor:
                    cursor.execute('''SELECT occurred_at, actor_email, actor_role, event_type, target, result, session_id, metadata
                        FROM kodf.audit_events WHERE occurred_at >= %s AND occurred_at < %s
                        AND (%s = '' OR actor_email = %s) AND (%s = '' OR event_type = %s)
                        ORDER BY occurred_at DESC LIMIT 500''', (lower, upper, user, user, event, event))
                    rows = cursor.fetchall()
            rows = [{**r, 'occurred_at': r['occurred_at'].astimezone(eastern).isoformat(), 'session_id': str(r['session_id']), 'metadata': json.dumps(r['metadata'], sort_keys=True)} for r in rows]
            table(rows)
            st.caption('Most recent 500 matching events. Narrow the dates to inspect older activity. No log editing or deletion is available in this app.')
            download(rows, 'audit_activity', 'Export filtered audit log')
        except Exception:
            st.warning('The audit reader is not configured or could not read the log. Configure a separate SELECT-only login.')
    st.caption('Export preparation is durably recorded before a download is offered. A later download click can fail to log during an outage, and browser save completion cannot be verified. Practice imports do not update production records.')
    with st.expander('One-time database setup and permissions'):
        st.write('Use an external PostgreSQL database with backups and a publicly trusted TLS certificate. The connection requires hostname and certificate verification; configure a provider CA bundle if your provider uses a private CA. Create two restricted login users using its admin console, then run this SQL as the owner. The app writer gets INSERT only; the reader gets SELECT only. Database owners can still modify logs, so this is not a tamper-proof archive.')
        st.code(AUDIT_SETUP_SQL, language='sql')
        st.write('Additional setup for permanent warrants and receipts:')
        st.code(WARRANT_SETUP_SQL, language='sql')
        st.code('''[audit]
write_database_url = "postgresql://RESTRICTED_WRITER:PRIVATE_PASSWORD@HOST/DATABASE"
read_database_url = "postgresql://SELECT_ONLY_READER:PRIVATE_PASSWORD@HOST/DATABASE"

# Add these keys within your EXISTING [access] section, before another heading:
# export_emails = ["treasurer@thekodf.org", "assit.treasurer@thekodf.org"]
# import_emails = []  # Administrator only until approved otherwise
# member_emails = ["member@thekodf.org"]  # Also add each to allowed_emails
# warrant_approver_emails = ["treasurer@thekodf.org", "assit.treasurer@thekodf.org"]
''', language='toml')
        st.caption('Store database URLs only in live Streamlit Secrets. Install psycopg[binary]>=3.3,<4 and Pillow>=12.3,<13 in your existing dependency configuration. Configure provider backups, retention, and database access controls separately. No external database has been provisioned by this code.')

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
    writer.writerows([{k: safe_csv_value(v) for k, v in r.items()} for r in rows])
    return buf.getvalue()


def download(rows, name, label='Download fictional report CSV'):
    if not rows:
        return
    if not file_permission('export'):
        st.caption('Exports require explicit permission. Viewing this report does not grant download access.')
        return
    if not st.session_state.get('audit_ready', False):
        st.caption('Exports are blocked until the audit database is configured and healthy.')
        return
    data = csv_data(rows)
    digest = hashlib.sha256(data.encode('utf-8')).hexdigest()
    context = (digest, st.session_state.get('reporting_period', 'All sample months'))
    metadata = {'report': name, 'period': context[1], 'row_count': len(rows), 'format': 'csv', 'sha256': digest}
    key = f'prepared_export_{name}'
    if st.button('Prepare ' + label.lower(), key=f'prepare_{name}'):
        if not file_permission('export'):
            audit_event('export_denied', name, 'denied', {'reason': 'permission'})
            st.session_state.pop(key, None)
            return
        if audit_event('export_prepared', name, metadata=metadata):
            st.session_state[key] = context
        else:
            st.session_state.pop(key, None)
            st.error('Export could not be logged. No download was prepared.')
    if st.session_state.get(key) == context:
        st.download_button(label, data, f'kodf_demo_{name}.csv', 'text/csv', key=f'download_{name}',
                           on_click=log_download, args=(name, metadata))
        st.caption('Preparation is logged before the file is offered. Download clicks are logged separately; they do not prove the file finished saving.')


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
        audit_event('dashboard_access_denied', 'dashboard', 'denied', {'reason': 'not_approved_or_unverified'})
        st.error('You do not have access to this dashboard.')
        st.button('Sign out', on_click=st.logout)
        st.stop()
    role = current_identity()[1]
    can_manage = role in {'Administrator', 'Finance'}
    pages = ['My Warrants'] if role == 'Member' else ['Overview', 'Budget', 'Close Summary']
    if can_manage:
        pages += ['Action Required', 'Accounts & Cash', 'History', 'Forecast', 'Transactions', 'Rentals', 'Processing', 'Funds & Grants', 'Reconciliation', 'Exceptions', 'Documents', 'Report Center', 'CSV Import', 'My Warrants', 'Warrant Review']
    if role == 'Administrator':
        pages += ['Connections', 'Security Activity']
    st.sidebar.title('KODF Finance')
    st.sidebar.caption(f'Access: {role}')
    st.sidebar.caption(f'Signed in as: {user_email}')
    st.sidebar.button('Sign out', on_click=audit_logout)
    if st.session_state.get('dashboard_page') not in pages:
        st.session_state['dashboard_page'] = pages[0]
    page = st.sidebar.radio('View', pages, key='dashboard_page')
    period = st.sidebar.selectbox('Reporting period', ['All sample months', '2026-Q2', '2026-Q3'] + MONTHS, key='reporting_period')
    as_of = st.sidebar.date_input('Action review date', date(2026, 10, 3))
    st.sidebar.caption('Reporting period filters financial reports. Cash is a September 30 snapshot; rentals and tasks use the action review date.')
    indices = quarter_indices(period)
    if page not in pages:
        st.error('You do not have access to this report.')
        st.stop()
    # Log a dashboard session once; retry after failures. Do not call it Google login.
    actor_key = (user_email, role)
    if st.session_state.get('audit_actor') != actor_key:
        st.session_state['audit_actor'] = actor_key
        st.session_state['audit_session_id'] = str(uuid.uuid4())
        st.session_state.pop('audit_session_logged', None)
        st.session_state.pop('audit_last_view', None)
        for key in list(st.session_state):
            if key.startswith('prepared_export_') or key in {'audit_upload_token', 'audit_validation_token', 'audit_imported_token', 'practice_import_rows'}:
                st.session_state.pop(key, None)
    healthy = True
    if st.session_state.get('audit_write_failed') and st.session_state.get('audit_session_logged'):
        healthy = audit_event('audit_recovery_check', 'audit_database')
    if not st.session_state.get('audit_session_logged'):
        healthy = audit_event('dashboard_session_started', 'dashboard')
        st.session_state['audit_session_logged'] = healthy
    view = (page, period, str(as_of))
    if healthy and st.session_state.get('audit_last_view') != view:
        healthy = audit_event('report_opened', page, metadata={'period': period, 'review_date': str(as_of)})
        if healthy:
            st.session_state['audit_last_view'] = view
    # Test connectivity; a previous failed write also requires a successful recovery event.
    try:
        with audit_connection() as conn:
            conn.execute('SELECT 1')
    except Exception:
        healthy = False
    st.session_state['audit_ready'] = healthy
    st.session_state['audit_write_failed'] = False if healthy else True
    st.sidebar.caption('Audit database: connected' if healthy else 'Audit database: not ready — file transfers blocked')
    if not healthy and role == 'Administrator':
        st.warning('Audit logging is not configured or unavailable. Open Security Activity for setup. Keep real financial data disconnected.')
    if st.session_state.get('audit_notice'):
        st.warning(st.session_state.pop('audit_notice'))
    income, expense = total(INCOME, indices), total(EXPENSES, indices)
    actions = action_rows(as_of, indices) if can_manage else []
    st.title('KODF Treasurer Dashboard')
    st.caption('Financial visibility · cash planning · collections · monthly close')
    st.info('DEMO — fictional financial reports. No banks or accounting systems are connected. Practice checklist/CSV changes are temporary. Submitted warrants and receipts are saved in PostgreSQL when configured; use fictional requests until launch approval.')
    st.caption('Sample data as of September 30, 2026 · Live refresh: none · September: preliminary · June–August: fictional approved examples')
    if can_manage:
        st.button(f'Action Required ({len(actions)})', type='primary', on_click=go, args=('Action Required',))
    elif role == 'Viewer':
        st.caption('Board view: summaries only. Ask Finance about unresolved items or preliminary figures.')

    if page == 'Overview':
        if '-Q' in period:
            quarterly_page(indices, can_manage)
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
        completed = [st.checkbox(task, key=f'close_{month}_{i}', on_change=record_practice_change, args=(f'close_{month}_{i}', f'{month}:{i}')) for i, task in enumerate(STEPS)]
        st.progress(sum(completed) / len(STEPS))
        st.write(f'{sum(completed)} of {len(STEPS)} practice steps complete.')
        note_key = f'close_note_{month}'
        st.text_area('Practice close notes', key=note_key, on_change=record_practice_change, args=(note_key, month))
        download([{'Month': month, 'Task': task, 'Practice checked': completed[i], 'Practice notes': st.session_state.get(note_key, '')} for i, task in enumerate(STEPS)], 'practice_close')

    elif page == 'Exceptions' and can_manage:
        st.subheader('Financial exception review')
        st.caption('Changes are session-only; marking an item resolved removes its practice task from Action Required. It does not change bookkeeping or create an audit record.')
        for issue in ISSUES:
            with st.expander(f"{issue['ID']} · {issue['Issue']} · {money(issue['Amount'])}"):
                st.write(issue['Item'])
                st.caption(f"Owner: {issue['Owner']} · Due: {issue['Due']}")
                st.selectbox('Practice status', ['Open', 'In review', 'Resolved'], key=f"issue_status_{issue['ID']}", on_change=record_practice_change, args=(f"issue_status_{issue['ID']}", issue['ID']))
                st.text_area('Practice resolution notes', key=f"issue_note_{issue['ID']}", on_change=record_practice_change, args=(f"issue_note_{issue['ID']}", issue['ID']))
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
            report = st.selectbox('Finance report', ['Monthly financial summary', 'Budget versus actual', 'Rental balances', 'Action queue', 'Processing breakdown', 'Grant balances', 'Quarterly summary'])
            datasets = {'Monthly financial summary': (summary_report(indices), ['Income', 'Expenses', 'Net income']), 'Budget versus actual': (budget_rows(indices), ['Budget', 'Actual', 'Remaining']), 'Rental balances': (rental_rows(as_of), ['Balance', 'Paid', 'Total']), 'Action queue': (actions, ['Amount']), 'Processing breakdown': (processor_rows(indices), ['Gross', 'Refunds', 'Fees', 'Expected net']), 'Grant balances': ([{**g, 'Remaining': g['Received'] - g['Spent']} for g in GRANTS], ['Received', 'Spent', 'Committed', 'Remaining'])}
            datasets['Quarterly summary'] = (quarterly_rows(indices), ['Income', 'Expenses', 'Net income'])
            rows, monetary = datasets[report]
            table(rows, monetary)
            download(rows, 'finance_report')
        st.divider()
        st.write('Planned delivery: weekly finance notifications; monthly board summaries after independent approval. Officer reports require an approved scope and recipient list.')
        st.caption('No email automation is active. Downloads contain fictional data. Production delivery needs an approved recipient list, scheduler, freshness checks, finance approval, and delivery logs.')

    elif page == 'My Warrants' and may_submit_warrant():
        my_warrants()

    elif page == 'Warrant Review' and can_manage:
        warrant_review()

    elif page == 'CSV Import' and can_manage:
        import_page()

    elif page == 'Security Activity' and role == 'Administrator':
        audit_page()

    elif page == 'Connections' and role == 'Administrator':
        st.subheader('Connection status and implementation roadmap')
        table([{'System': system, 'Status': 'Not connected', 'Next step': task} for system, task in [('QuickBooks', 'Activate approved subscription; validate one month'), ('Banks', 'Connect to QuickBooks through authorized bank user'), ('Square / Stripe', 'Validate fees, refunds, transfers, and settlement mapping'), ('Acuity', 'Match booking and payment IDs'), ('Google Drive', 'Configure restricted document folders'), ('Database', 'Add shared durable tasks, approval records, and audit history'), ('Scheduled reports', 'Configure reviewed recipients and approved report delivery')]])
        st.caption('This screen does not collect credentials or activate integrations. Google authentication is already handled separately through existing [auth] settings.')
        with st.expander('Access diagnostics'):
            st.write(f"Admin role configured: {'admin_emails' in access}")
            st.write(f"Email matches admin list: {user_email in emails('admin_emails')}")
    st.divider()
    st.caption('KODF · Expanded Treasurer Dashboard · Fictional demonstration. Finance owns categorization, reconciliation, and financial approval; IT maintains the technology.')



WARRANT_SETUP_SQL = '''-- Run after AUDIT_SETUP_SQL, as the database owner.
CREATE TABLE IF NOT EXISTS kodf.warrants (
 id uuid PRIMARY KEY, submitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 requester_email text NOT NULL, request_type text NOT NULL CHECK (request_type IN ('Reimbursement','Refund')),
 expense_date date NOT NULL, description text NOT NULL CHECK (length(description) BETWEEN 10 AND 1000),
 amount numeric(12,2) NOT NULL CHECK (amount > 0 AND amount <= 1000000),
 payment_reference text NOT NULL DEFAULT '', receipt_name text NOT NULL,
 receipt_sha256 text NOT NULL, receipt_data bytea NOT NULL CHECK (octet_length(receipt_data) <= 5242880)
);
CREATE TABLE IF NOT EXISTS kodf.warrant_decisions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id uuid NOT NULL REFERENCES kodf.warrants(id),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 actor_email text NOT NULL, status text NOT NULL CHECK (status IN ('In review','Approved','Rejected','Paid')),
 note text NOT NULL CHECK (length(note) BETWEEN 5 AND 1000), payment_reference text NOT NULL DEFAULT ''
);
REVOKE ALL ON kodf.warrants, kodf.warrant_decisions FROM PUBLIC, kodf_audit_writer, kodf_audit_reader;
GRANT INSERT ON kodf.warrants TO kodf_audit_writer;
GRANT SELECT ON kodf.warrants, kodf.warrant_decisions TO kodf_audit_reader;
CREATE OR REPLACE FUNCTION kodf.record_warrant_decision(
 p_id uuid, p_actor text, p_role text, p_expected text, p_status text, p_note text, p_reference text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE owner_email text; old_status text; approver_email text;
BEGIN
 IF p_role NOT IN ('Administrator','Finance') THEN RAISE EXCEPTION 'Denied'; END IF;
 SELECT requester_email INTO owner_email FROM kodf.warrants WHERE id=p_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown warrant'; END IF;
 SELECT status INTO old_status FROM kodf.warrant_decisions WHERE request_id=p_id ORDER BY id DESC LIMIT 1;
 old_status := coalesce(old_status,'Submitted');
 IF old_status <> p_expected THEN RAISE EXCEPTION 'Changed by another reviewer'; END IF;
 IF owner_email = p_actor THEN RAISE EXCEPTION 'Independent reviewer required'; END IF;
 IF NOT ((old_status='Submitted' AND p_status IN ('In review','Rejected'))
   OR (old_status='In review' AND p_status IN ('Approved','Rejected'))
   OR (old_status='Approved' AND p_status='Paid')) THEN RAISE EXCEPTION 'Invalid transition'; END IF;
 IF p_status='Paid' THEN
   SELECT actor_email INTO approver_email FROM kodf.warrant_decisions
   WHERE request_id=p_id AND status='Approved' ORDER BY id DESC LIMIT 1;
   IF approver_email=p_actor THEN RAISE EXCEPTION 'Separate payment recorder required'; END IF;
   IF length(trim(p_reference)) < 3 THEN RAISE EXCEPTION 'Payment reference required'; END IF;
 END IF;
 INSERT INTO kodf.warrant_decisions(request_id,actor_email,status,note,payment_reference)
 VALUES(p_id,p_actor,p_status,p_note,p_reference);
END; $$;
REVOKE ALL ON FUNCTION kodf.record_warrant_decision(uuid,text,text,text,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION kodf.record_warrant_decision(uuid,text,text,text,text,text,text,text) TO kodf_audit_writer;
-- Trusted app checks current Google identity and role before calling this function.
-- Use a non-superuser function owner; do not grant ownership to app login users.
'''


def quarter_indices(period):
    if period == 'All sample months':
        return list(range(len(MONTHS)))
    if '-Q' in period:
        year, quarter = period.split('-Q')
        return [i for i, month in enumerate(MONTHS) if month.startswith(year) and (int(month[5:7]) - 1) // 3 + 1 == int(quarter)]
    return [i for i, month in enumerate(MONTHS) if month == period]


def quarterly_rows(indices):
    groups = {}
    for i in indices:
        key = f"{MONTHS[i][:4]}-Q{(int(MONTHS[i][5:7]) - 1) // 3 + 1}"
        groups.setdefault(key, []).append(i)
    return [{'Quarter': key, 'Months available': len(items), 'Coverage': 'Complete quarter' if len(items) == 3 else 'Partial quarter — missing months',
             'Income': total(INCOME, items), 'Expenses': total(EXPENSES, items), 'Net income': total(INCOME, items) - total(EXPENSES, items),
             'Approval': 'Sample approved' if len(items) == 3 and all(i < 3 for i in items) else 'Preliminary / incomplete'} for key, items in groups.items()]


def may_submit_warrant():
    return current_identity()[1] in {'Member', 'Finance', 'Administrator'}


def may_decide_warrant():
    email, role, _ = current_identity()
    access = st.secrets.get('access', {})
    approved = access.get('warrant_approver_emails', access.get('finance_emails', []))
    return role in {'Finance', 'Administrator'} and email in {str(e).strip().lower() for e in approved}


def validate_warrant(kind, expense_date, description, amount, reference):
    description, reference = description.strip(), reference.strip()
    if kind not in {'Reimbursement', 'Refund'}:
        raise ValueError('Choose reimbursement or refund.')
    if expense_date > date.today():
        raise ValueError('The expense/payment date cannot be in the future.')
    if not 10 <= len(description) <= 1000:
        raise ValueError('Description must contain 10–1,000 characters.')
    try:
        price = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError('Enter a valid dollar amount.') from None
    if not price.is_finite() or price <= 0 or price > 1000000 or price != price.quantize(Decimal('.01')):
        raise ValueError('Amount must be greater than zero, at most $1,000,000, and use at most two decimal places.')
    if len(reference) > 150 or (kind == 'Refund' and len(reference) < 3):
        raise ValueError('Refunds require the original payment reference; maximum 150 characters.')
    return description, price, reference


def normalize_receipt(data):
    from PIL import Image
    import warnings
    if not data or len(data) > 5 * 1024 * 1024:
        raise ValueError('Upload a receipt image no larger than 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=['JPEG', 'PNG']) as image:
                if image.width * image.height > 12000000 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Use a single receipt image with at most 12 million pixels.')
                image.load()
                # Re-encode pixels into JPEG: strip attached payloads and image metadata.
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=90)
        cleaned = output.getvalue()
        if len(cleaned) > 5 * 1024 * 1024:
            raise ValueError('Receipt image is too large after validation.')
        return cleaned
    except Exception:
        raise ValueError('Receipt must be a readable, single JPEG or PNG image within the limits. PDF receipts are not enabled yet.') from None


def insert_audit(conn, event_type, target, result='success', metadata=None):
    email, role, subject = current_identity()
    conn.execute('''INSERT INTO kodf.audit_events
      (id,actor_email,actor_subject,actor_role,session_id,event_type,target,result,metadata)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)''',
      (str(uuid.uuid4()), email, subject, role, st.session_state.setdefault('audit_session_id', str(uuid.uuid4())), event_type, str(target), result, json.dumps(metadata or {}, default=str)))


def warrant_records(all_members=False):
    from psycopg.rows import dict_row
    email, role, _ = current_identity()
    if role == 'Denied' or (all_members and role not in {'Finance', 'Administrator'}):
        raise PermissionError('Denied')
    with audit_connection(reader=True) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('''SELECT w.id::text, w.submitted_at, w.requester_email, w.request_type, w.expense_date,
              w.description, w.amount, w.payment_reference, w.receipt_name,
              coalesce(d.status,'Submitted') AS status, d.note AS review_note,
              d.payment_reference AS paid_reference, d.occurred_at AS status_at
              FROM kodf.warrants w LEFT JOIN LATERAL
              (SELECT * FROM kodf.warrant_decisions WHERE request_id=w.id ORDER BY id DESC LIMIT 1) d ON true
              WHERE (%s OR w.requester_email=%s) ORDER BY w.submitted_at DESC LIMIT 500''', (all_members, email))
            rows = cur.fetchall()
    return [{**r, 'amount': float(r['amount']), 'submitted_at': r['submitted_at'].astimezone(ZoneInfo('America/New_York')).isoformat()} for r in rows]


def receipt_view(request_id):
    from psycopg.rows import dict_row
    email, role, _ = current_identity()
    if role == 'Denied':
        return
    with audit_connection(reader=True) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT receipt_data FROM kodf.warrants WHERE id=%s AND (%s OR requester_email=%s)',
                        (request_id, role in {'Finance', 'Administrator'}, email))
            row = cur.fetchone()
    if row and audit_event('receipt_viewed', request_id):
        st.image(bytes(row['receipt_data']), caption='Validated receipt image')
    elif row:
        st.error('Receipt access could not be logged.')


def my_warrants():
    st.subheader('My reimbursement and refund warrants')
    st.caption('Request payment; Finance reviews the receipt and approves it. Submission does not send money or post an accounting expense. Use fictional test requests until the foundation approves this workflow.')
    if not may_submit_warrant():
        st.info('IT must approve your member submission access.')
        return
    if not st.session_state.get('audit_ready'):
        st.warning('Submission and receipt uploads are blocked until the database is connected.')
        return
    draft_id = st.session_state.setdefault('warrant_draft_id', str(uuid.uuid4()))
    with st.form('warrant_form', clear_on_submit=True):
        kind = st.selectbox('Request type', ['Reimbursement', 'Refund'])
        expense_date = st.date_input('Expense or original payment date', date.today())
        description = st.text_area('Describe the purchase or reason for refund', max_chars=1000)
        amount = st.number_input('Amount requested ($)', min_value=0.0, max_value=1000000.0, step=1.0, format='%.2f')
        reference = st.text_input('Original payment reference (required for refunds)', max_chars=150)
        receipt = st.file_uploader('Receipt — JPEG/PNG, maximum 5 MB', type=['jpg', 'jpeg', 'png'])
        submitted = st.form_submit_button('Submit warrant for review')
    if submitted:
        try:
            if not may_submit_warrant():
                raise PermissionError('Submission access changed.')
            description, price, reference = validate_warrant(kind, expense_date, description, amount, reference)
            cleaned = normalize_receipt(receipt.getvalue() if receipt else b'')
            digest = hashlib.sha256(cleaned).hexdigest()
            with audit_connection() as conn:
                conn.execute('''INSERT INTO kodf.warrants
                  (id,requester_email,request_type,expense_date,description,amount,payment_reference,receipt_name,receipt_sha256,receipt_data)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                  (draft_id, current_identity()[0], kind, expense_date, description, price, reference, 'receipt.jpg', digest, cleaned))
                insert_audit(conn, 'receipt_uploaded', draft_id, metadata={'filename': 'receipt.jpg', 'size_bytes': len(cleaned), 'sha256': digest})
                insert_audit(conn, 'warrant_submitted', draft_id, metadata={'request_type': kind, 'amount': str(price), 'sha256': digest})
            st.session_state['warrant_draft_id'] = str(uuid.uuid4())
            st.success(f'Warrant submitted. Reference: {draft_id}')
        except ValueError as exc:
            audit_event('warrant_validation_failed', draft_id, 'rejected', {'reason': 'validation'})
            st.error(str(exc))
        except Exception:
            st.error('Warrant was not saved. Verify database setup, then check My Warrants before retrying.')
    try:
        rows = warrant_records()
        table(rows, ['amount'])
        st.caption('Most recent 500 of your requests. Receipt images and descriptions are visible only to you and authorized Finance/Administrator users.')
        if rows:
            chosen = st.selectbox('Choose your warrant', [r['id'] for r in rows])
            if st.button('View my receipt'):
                receipt_view(chosen)
    except Exception:
        st.warning('Warrant storage is not ready. Run the warrant setup SQL in Security Activity.')


def warrant_review():
    st.subheader('Finance warrant review')
    if current_identity()[1] not in {'Finance', 'Administrator'}:
        st.stop()
    if not st.session_state.get('audit_ready'):
        st.warning('Review actions are blocked until audit logging is connected.')
        return
    try:
        rows = warrant_records(all_members=True)
    except Exception:
        st.warning('Warrant storage is not ready. Run the warrant setup SQL in Security Activity.')
        return
    status = st.selectbox('Filter status', ['All', 'Submitted', 'In review', 'Approved', 'Paid', 'Rejected'])
    filtered = [r for r in rows if status == 'All' or r['status'] == status]
    table(filtered, ['amount'])
    download(filtered, 'warrants')
    st.caption('Most recent 500 requests. Submitted/approved warrants are not new posted expenses. Marking Paid records a manual payment; this app never initiates a transfer.')
    if not filtered:
        return
    chosen = st.selectbox('Warrant to review', [r['id'] for r in filtered])
    record = next(r for r in filtered if r['id'] == chosen)
    if st.button('View receipt for review'):
        receipt_view(chosen)
    if not may_decide_warrant():
        st.info('You can inspect warrants, but only designated financial approvers may change their status. IT access alone does not grant financial approval authority.')
        return
    if record['requester_email'] == current_identity()[0]:
        st.info('A different authorized reviewer must review your own warrant.')
        return
    choices = {'Submitted': ['In review', 'Rejected'], 'In review': ['Approved', 'Rejected'], 'Approved': ['Paid']}.get(record['status'], [])
    if choices:
        with st.form('warrant_decision'):
            decision = st.selectbox('Next status', choices)
            note = st.text_area('Review / payment notes (required)', max_chars=1000)
            reference = st.text_input('Payment transaction reference (required for Paid)', max_chars=150)
            confirm = st.checkbox('I reviewed the receipt and applicable approval requirements')
            save = st.form_submit_button('Save review decision')
        if save:
            if not confirm or not 5 <= len(note.strip()) <= 1000 or (decision == 'Paid' and len(reference.strip()) < 3):
                st.error('Confirm review, enter notes, and supply a payment reference when marking Paid.')
                return
            try:
                email, role, _ = current_identity()
                if not may_decide_warrant():
                    raise PermissionError('Denied')
                with audit_connection() as conn:
                    conn.execute('SELECT kodf.record_warrant_decision(%s,%s,%s,%s,%s,%s,%s,%s)',
                                 (chosen, email, role, record['status'], decision, note.strip(), reference.strip()))
                    insert_audit(conn, 'warrant_status_changed', chosen, metadata={'old_status': record['status'], 'new_status': decision, 'note_length': len(note.strip())})
                st.success('Decision saved with an audit event. Refresh this page to see the new status.')
            except Exception:
                st.error('Decision was not saved. Another reviewer may have changed it, or independent payment recording is required. The approver cannot mark their own approval Paid.')


def quarterly_page(indices, can_manage):
    st.subheader('Quarterly financial summaries')
    rows = quarterly_rows(indices)
    table(rows, ['Income', 'Expenses', 'Net income'])
    st.caption('Calendar quarters. The sample begins June 2026: Q2 is missing April and May; Q3 includes July–September but September is preliminary. These are not complete approved quarterly statements.')
    if can_manage:
        download(rows, 'quarterly_summary')
        st.subheader('Warrant activity — separate from accounting totals')
        try:
            warrants = warrant_records(all_members=True)
            grouped = {}
            for r in warrants:
                when = r['expense_date']
                key = f'{when.year}-Q{(when.month - 1) // 3 + 1}'
                group = grouped.setdefault(key, {'Quarter': key, 'Requests': 0, 'Requested': 0.0, 'Pending': 0.0, 'Approved unpaid': 0.0, 'Marked paid': 0.0, 'Rejected': 0.0})
                group['Requests'] += 1
                group['Requested'] += r['amount']
                field = 'Pending' if r['status'] in {'Submitted','In review'} else 'Approved unpaid' if r['status']=='Approved' else 'Marked paid' if r['status']=='Paid' else 'Rejected'
                group[field] += r['amount']
            table(list(grouped.values()), ['Requested','Pending','Approved unpaid','Marked paid','Rejected'])
            st.caption('Based on expense/original-payment quarter, for the most recent 500 warrants. This is request activity, not payments by payment date. Never add these amounts to financial expenses automatically; Finance must match them to QuickBooks to avoid double counting.')
        except Exception:
            st.info('Warrant quarterly activity becomes available after database setup.')


if __name__ == '__main__':
    main()
