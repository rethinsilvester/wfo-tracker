import os
import pandas as pd
from flask import Flask, render_template, jsonify, request
from datetime import datetime
import glob
import logging
import re
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'wms-uv-admin-tracker-2025'

# Configuration
CONFIG = {
    'team_name': 'WMS/UV Admin',
    'excel_pattern': '*UV-WCS*.xlsx',
    'data_folder': 'data',
    'wfo_target_days': 12  # Target WFO days per month
}

os.makedirs(CONFIG['data_folder'], exist_ok=True)
os.makedirs('static/photos', exist_ok=True)


def get_employee_photo(name, person_id=''):
    """Find employee photo by name or ID, return URL or None"""
    photo_dir = 'static/photos'
    extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']

    # Try by name first
    for ext in extensions:
        photo_path = os.path.join(photo_dir, f"{name}{ext}")
        if os.path.exists(photo_path):
            return f"/static/photos/{name}{ext}"

    # Try by person_id
    if person_id:
        for ext in extensions:
            photo_path = os.path.join(photo_dir, f"{person_id}{ext}")
            if os.path.exists(photo_path):
                return f"/static/photos/{person_id}{ext}"

    return None


def find_latest_excel():
    """Find the latest Excel file"""
    try:
        pattern = os.path.join(CONFIG['data_folder'], CONFIG['excel_pattern'])
        files = glob.glob(pattern)
        if not files:
            files = glob.glob(os.path.join(CONFIG['data_folder'], '*.xlsx'))
        if files:
            return max(files, key=os.path.getmtime)
        return None
    except Exception as e:
        logger.error(f"Error finding Excel: {e}")
        return None


def parse_month_year(sheet_name):
    """Extract month and year from sheet name like 'UV-WMS Admin January 2026'"""
    month_order = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                   'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
                   'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
                   'july': 7, 'august': 8, 'september': 9, 'october': 10,
                   'november': 11, 'december': 12}

    month_num = None
    year = None

    for word in sheet_name.lower().split():
        if word in month_order:
            month_num = month_order[word]
        if word.isdigit() and len(word) == 4:
            year = int(word)

    return month_num, year


def is_current_or_past_month(sheet_name):
    """Check if a sheet represents the current month or a past month"""
    month_num, year = parse_month_year(sheet_name)

    if month_num is None or year is None:
        return True  # If we can't parse, assume it's valid

    now = datetime.now()
    current_year = now.year
    current_month = now.month

    if year < current_year:
        return True
    elif year > current_year:
        return False
    else:
        return month_num <= current_month


def sort_months(month_names):
    """Sort months chronologically with year support"""
    def get_sort_key(name):
        month_num, year = parse_month_year(name)
        if month_num is None:
            month_num = 0
        if year is None:
            year = 2000
        return (year, month_num)

    return sorted(month_names, key=get_sort_key)


def get_current_month_sheet(month_names):
    """Find the sheet matching current month/year, or closest previous"""
    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # First try exact match for current month/year
    for name in month_names:
        year, month = parse_month_year(name)
        if year == current_year and month == current_month:
            return name

    # Otherwise find the closest month <= current date
    sorted_months = sort_months(month_names)
    best_match = sorted_months[0] if sorted_months else None

    for name in sorted_months:
        month, year = parse_month_year(name)
        if year is None:
            continue
        if (year, month) <= (current_year, current_month):
            best_match = name
        else:
            break

    return best_match


def format_date_column(col):
    """Format a date column to a readable string"""
    if isinstance(col, datetime):
        return col.strftime('%d %b')  # e.g., "01 Jan"
    elif hasattr(col, 'strftime'):
        return col.strftime('%d %b')
    return str(col)


def load_data(include_future=False):
    """Load and process Excel data

    Args:
        include_future: If True, include future months. If False, only current and past months.
    """
    try:
        filepath = find_latest_excel()
        if not filepath:
            return None, None

        excel = pd.read_excel(filepath, sheet_name=None)
        monthly_data = {}

        for sheet_name, df in excel.items():
            if df.empty or len(df) < 2:
                continue

            # Filter out future months for attendance (unless include_future is True)
            if not include_future and not is_current_or_past_month(sheet_name):
                logger.info(f"Skipping future month sheet: {sheet_name}")
                continue

            employees = []

            # Get date columns (starting from index 5)
            date_cols = []
            date_col_map = {}  # Maps formatted string to original column
            weekend_count = 0
            holiday_dates = set()

            for i, col in enumerate(df.columns):
                if i >= 5:
                    formatted = format_date_column(col)
                    date_cols.append(formatted)
                    date_col_map[formatted] = col

                    # Check if weekend
                    if isinstance(col, datetime):
                        if col.weekday() >= 5:  # 5=Saturday, 6=Sunday
                            weekend_count += 1

            seen = set()

            # Start from row 1 (row 0 often has day names like "Thursday", "Friday")
            start_row = 1
            # Check if first data row has actual employee data
            if len(df) > 0:
                first_val = df.iloc[0, 0]
                if pd.isna(first_val) or str(first_val).strip() in ['', 'nan']:
                    start_row = 1
                elif str(first_val).strip().lower() in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                    start_row = 1

            # First pass: identify company holidays (dates where status is HOLIDAY for any employee)
            for idx in range(start_row, len(df)):
                row = df.iloc[idx]
                name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
                if not name or name.lower() in ['employee name', 'nan', '']:
                    continue

                for formatted_date, orig_col in date_col_map.items():
                    val = row[orig_col] if orig_col in row.index else None
                    if pd.notna(val):
                        status = str(val).strip().upper()
                        if status in ['HOLIDAY', 'INDIA HOLIDAY']:
                            holiday_dates.add(formatted_date)

            # Calculate working days (excluding weekends and company holidays)
            total_days = len(date_cols)
            working_days = total_days - weekend_count - len(holiday_dates)

            # Second pass: extract employee data
            for idx in range(start_row, len(df)):
                row = df.iloc[idx]
                name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''

                if not name or name.lower() in ['employee name', 'nan', ''] or name in seen:
                    continue

                seen.add(name)

                daily = {}
                for formatted_date, orig_col in date_col_map.items():
                    val = row[orig_col] if orig_col in row.index else None
                    if pd.notna(val):
                        status = str(val).strip()
                        if status and status.lower() not in ['nan', 'saturday', 'sunday']:
                            daily[formatted_date] = status

                if daily or name:  # Include employee even if no attendance data yet
                    employees.append({
                        'name': name,
                        'person_id': str(int(row.iloc[1])) if pd.notna(row.iloc[1]) else '',
                        'department': str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else '',
                        'daily_status': daily,
                        'month': sheet_name
                    })

            if employees:
                monthly_data[sheet_name] = {
                    'employees': employees,
                    'date_columns': date_cols,
                    'working_days': working_days,
                    'total_days': total_days,
                    'weekend_count': weekend_count,
                    'holiday_count': len(holiday_dates)
                }

        months = sort_months(list(monthly_data.keys()))
        sorted_data = {m: monthly_data[m] for m in months}

        return sorted_data, {
            'file': os.path.basename(filepath),
            'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M'),
            'months': months
        }

    except Exception as e:
        logger.error(f"Error loading data: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, None


def calc_stats(daily_status):
    """Calculate employee statistics"""
    stats = {'wfo': 0, 'wfh': 0, 'leave': 0, 'sl': 0, 'pl': 0, 'holiday': 0, 'total': 0}

    for status in daily_status.values():
        s = status.upper().strip()
        stats['total'] += 1
        if s == 'WFO':
            stats['wfo'] += 1
        elif s == 'WFH':
            stats['wfh'] += 1
        elif s in ['SL', 'SICK LEAVE']:
            stats['sl'] += 1
            stats['leave'] += 1
        elif s in ['LEAVE', 'PLANNED LEAVE', 'PL']:
            stats['pl'] += 1
            stats['leave'] += 1
        elif s in ['INDIA HOLIDAY', 'HOLIDAY']:
            stats['holiday'] += 1

    working = stats['wfo'] + stats['wfh']
    stats['wfo_pct'] = round((stats['wfo'] / working * 100), 1) if working > 0 else 0
    stats['wfh_pct'] = round((stats['wfh'] / working * 100), 1) if working > 0 else 0
    stats['working'] = working

    return stats


def extract_leave_data_by_year(year=None):
    """Extract leave data for a specific year for Leave Tracker"""
    data, meta = load_data(include_future=True)

    if not data:
        return None, None, [], []

    # Get all available years from the data
    available_years = set()
    for month_name in data.keys():
        _, sheet_year = parse_month_year(month_name)
        if sheet_year:
            available_years.add(sheet_year)

    available_years = sorted(available_years, reverse=True)

    # Default to current year if not specified
    if year is None:
        year = datetime.now().year

    # Aggregate leave data per employee for the selected year
    employee_leaves = defaultdict(lambda: {
        'name': '',
        'person_id': '',
        'sick_leave': [],
        'planned_leave': [],
        'total_sl': 0,
        'total_pl': 0,
        'total_leave': 0,
        'upcoming_leaves': [],
        'past_leaves': []
    })

    # Collect company holidays for the selected year
    company_holidays = []
    seen_holidays = set()

    for month_name, month_data in data.items():
        _, sheet_year = parse_month_year(month_name)

        # Skip months not in selected year
        if sheet_year != year:
            continue

        is_future = not is_current_or_past_month(month_name)

        for emp in month_data['employees']:
            emp_name = emp['name']
            employee_leaves[emp_name]['name'] = emp_name
            employee_leaves[emp_name]['person_id'] = emp.get('person_id', '')

            for date_str, status in emp['daily_status'].items():
                status_upper = status.upper().strip()

                leave_entry = {
                    'month': month_name,
                    'date': date_str,
                    'status': status_upper,
                    'is_future': is_future
                }

                if status_upper in ['SL', 'SICK LEAVE']:
                    employee_leaves[emp_name]['sick_leave'].append(leave_entry)
                    employee_leaves[emp_name]['total_sl'] += 1
                    if is_future:
                        employee_leaves[emp_name]['upcoming_leaves'].append(leave_entry)
                    else:
                        employee_leaves[emp_name]['past_leaves'].append(leave_entry)

                elif status_upper in ['LEAVE', 'PLANNED LEAVE', 'PL']:
                    employee_leaves[emp_name]['planned_leave'].append(leave_entry)
                    employee_leaves[emp_name]['total_pl'] += 1
                    if is_future:
                        employee_leaves[emp_name]['upcoming_leaves'].append(leave_entry)
                    else:
                        employee_leaves[emp_name]['past_leaves'].append(leave_entry)

                # Collect company holidays
                elif status_upper in ['HOLIDAY', 'INDIA HOLIDAY']:
                    holiday_key = f"{date_str}_{month_name}"
                    if holiday_key not in seen_holidays:
                        seen_holidays.add(holiday_key)
                        month_num, _ = parse_month_year(month_name)
                        company_holidays.append({
                            'date': date_str,
                            'month': month_name,
                            'month_num': month_num or 0
                        })

    # Calculate totals
    for emp_name in employee_leaves:
        employee_leaves[emp_name]['total_leave'] = (
            employee_leaves[emp_name]['total_sl'] +
            employee_leaves[emp_name]['total_pl']
        )

    # Sort holidays by month and day
    def sort_holiday(h):
        try:
            day = int(h['date'].split()[0])
            return (h['month_num'], day)
        except:
            return (0, 0)

    company_holidays.sort(key=sort_holiday)

    # Group holidays by month
    month_names = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    holidays_by_month = defaultdict(list)
    for h in company_holidays:
        try:
            day = int(h['date'].split()[0])
            month_name = month_names[h['month_num']] if h['month_num'] else 'Unknown'
            holidays_by_month[month_name].append(day)
        except:
            pass

    # Convert to sorted list of tuples
    holidays_grouped = []
    for i, m in enumerate(month_names[1:], 1):
        if m in holidays_by_month:
            days = sorted(holidays_by_month[m])
            holidays_grouped.append({
                'month': m,
                'days': ', '.join(str(d).zfill(2) for d in days),
                'count': len(days)
            })

    total_holidays = len(company_holidays)

    # Build calendar data for calendar view (all leaves for all employees)
    calendar_events = []
    for emp_name, emp_data in employee_leaves.items():
        for leave in emp_data['sick_leave'] + emp_data['planned_leave']:
            try:
                day = int(leave['date'].split()[0])
                month_num, _ = parse_month_year(leave['month'])
                if month_num:
                    leave_type = 'SL' if leave['status'] in ['SL', 'SICK LEAVE'] else 'PL'
                    calendar_events.append({
                        'name': emp_name,
                        'day': day,
                        'month': month_num,
                        'type': leave_type,
                        'is_future': leave['is_future']
                    })
            except:
                pass

    return dict(employee_leaves), meta, available_years, holidays_grouped, total_holidays, calendar_events


@app.route('/')
def index():
    """Landing page with team summary - only current and past months"""
    data, meta = load_data(include_future=False)

    if not data:
        return render_template('no_data.html')

    available_months = list(data.keys())
    month = request.args.get('month')

    # Default to current month if not specified or invalid
    if not month or month not in data:
        month = get_current_month_sheet(available_months)
        if not month:
            month = available_months[-1]  # Fallback to latest

    month_data = data[month]
    working_days = month_data.get('working_days', 20)  # Default to 20 if not calculated
    admins = []

    for emp in month_data['employees']:
        stats = calc_stats(emp['daily_status'])
        # Calculate WFO percentage based on target days
        stats['wfo_pct'] = round((stats['wfo'] / CONFIG['wfo_target_days'] * 100), 1) if CONFIG['wfo_target_days'] > 0 else 0
        admins.append({
            'name': emp['name'],
            'person_id': emp['person_id'],
            'photo': get_employee_photo(emp['name'], emp['person_id']),
            'stats': stats
        })

    # Team totals - based on target days (100% = everyone meets target)
    total_wfo = sum(a['stats']['wfo'] for a in admins)
    num_members = len(admins)
    total_target = CONFIG['wfo_target_days'] * num_members
    team_wfo_pct = round((total_wfo / total_target * 100), 1) if total_target > 0 else 0

    # Find top performer(s) - "Office Freaks"
    if admins:
        max_wfo = max(a['stats']['wfo'] for a in admins)
        office_freaks = [a['name'] for a in admins if a['stats']['wfo'] == max_wfo and max_wfo > 0]
    else:
        office_freaks = []
        max_wfo = 0

    return render_template('index.html',
                         admins=admins,
                         month=month,
                         months=available_months,
                         team_wfo_pct=team_wfo_pct,
                         working_days=working_days,
                         wfo_target_days=CONFIG['wfo_target_days'],
                         office_freaks=office_freaks,
                         max_wfo=max_wfo,
                         meta=meta)


@app.route('/admin/<n>')
def admin_calendar(n):
    """Calendar view for specific admin"""
    data, meta = load_data(include_future=False)

    if not data:
        return render_template('no_data.html')

    available_months = list(data.keys())
    month = request.args.get('month')

    # Default to current month if not specified or invalid
    if not month or month not in data:
        month = get_current_month_sheet(available_months)
        if not month:
            month = available_months[-1]

    month_data = data[month]
    working_days = month_data.get('working_days', 20)
    admin = None

    for emp in month_data['employees']:
        if emp['name'] == n:
            admin = emp
            break

    if not admin:
        return render_template('not_found.html', name=n)

    stats = calc_stats(admin['daily_status'])
    # Calculate WFO percentage based on target days
    stats['wfo_pct'] = round((stats['wfo'] / CONFIG['wfo_target_days'] * 100), 1) if CONFIG['wfo_target_days'] > 0 else 0

    # Get photo URL
    photo = get_employee_photo(admin['name'], admin.get('person_id', ''))

    # Build calendar data with all dates from the sheet
    calendar_data = []
    for date_str in month_data['date_columns']:
        status = admin['daily_status'].get(date_str, '')
        if status:  # Only show days with data
            calendar_data.append({
                'date': date_str,
                'status': status.upper().strip()
            })

    return render_template('calendar.html',
                         admin=admin,
                         stats=stats,
                         photo=photo,
                         calendar_data=calendar_data,
                         month=month,
                         months=available_months,
                         working_days=working_days,
                         wfo_target_days=CONFIG['wfo_target_days'],
                         meta=meta)


@app.route('/leave-tracker')
def leave_tracker():
    """Leave Tracker - reads ALL months including future, filtered by year"""
    # Get year from query param, default to current year
    year_param = request.args.get('year')
    current_year = datetime.now().year

    if year_param:
        try:
            selected_year = int(year_param)
        except ValueError:
            selected_year = current_year
    else:
        selected_year = current_year

    employee_leaves, meta, available_years, holidays_grouped, total_holidays, calendar_events = extract_leave_data_by_year(selected_year)

    if not employee_leaves:
        return render_template('no_data.html')

    # Convert to list and sort by total leave (descending)
    leave_list = list(employee_leaves.values())
    leave_list.sort(key=lambda x: x['total_leave'], reverse=True)

    # Add photos
    for emp in leave_list:
        emp['photo'] = get_employee_photo(emp['name'], emp.get('person_id', ''))

    return render_template('leave_tracker.html',
                         employees=leave_list,
                         meta=meta,
                         selected_year=selected_year,
                         available_years=available_years,
                         holidays_grouped=holidays_grouped,
                         total_holidays=total_holidays,
                         calendar_events=calendar_events)


@app.route('/api/refresh')
def refresh():
    """API to check data status"""
    data, meta = load_data()
    if data:
        return jsonify({'status': 'ok', 'meta': meta})
    return jsonify({'status': 'no_data'}), 404


@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting WMS/UV Admin WFO Tracker on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
