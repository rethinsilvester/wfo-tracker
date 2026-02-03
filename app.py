import os
import pandas as pd
from flask import Flask, render_template, jsonify, request
from datetime import datetime
import glob
import logging

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


def sort_months(month_names):
    """Sort months chronologically with year support"""
    month_order = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                   'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
                   'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
                   'july': 7, 'august': 8, 'september': 9, 'october': 10,
                   'november': 11, 'december': 12}
    
    def get_sort_key(name):
        month_num = 0
        year = 2000  # default
        
        for word in name.lower().split():
            if word in month_order:
                month_num = month_order[word]
            # Check for year (4 digit number)
            if word.isdigit() and len(word) == 4:
                year = int(word)
        
        return (year, month_num)
    
    return sorted(month_names, key=get_sort_key)


def get_current_month_sheet(month_names):
    """Find the sheet matching current month/year, or closest previous"""
    month_order = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                   'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
                   'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
                   'july': 7, 'august': 8, 'september': 9, 'october': 10,
                   'november': 11, 'december': 12}
    
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    
    def parse_sheet(name):
        month_num = 0
        year = None
        for word in name.lower().split():
            if word in month_order:
                month_num = month_order[word]
            if word.isdigit() and len(word) == 4:
                year = int(word)
        return (year, month_num)
    
    # First try exact match for current month/year
    for name in month_names:
        year, month = parse_sheet(name)
        if year == current_year and month == current_month:
            return name
    
    # Otherwise find the closest month <= current date
    sorted_months = sort_months(month_names)
    best_match = sorted_months[0] if sorted_months else None
    
    for name in sorted_months:
        year, month = parse_sheet(name)
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


def load_data():
    """Load and process Excel data"""
    try:
        filepath = find_latest_excel()
        if not filepath:
            return None, None
        
        excel = pd.read_excel(filepath, sheet_name=None)
        monthly_data = {}
        
        for sheet_name, df in excel.items():
            if df.empty or len(df) < 2:
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
                        'daily_status': daily
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
    stats = {'wfo': 0, 'wfh': 0, 'leave': 0, 'holiday': 0, 'total': 0}
    
    for status in daily_status.values():
        s = status.upper().strip()
        stats['total'] += 1
        if s == 'WFO':
            stats['wfo'] += 1
        elif s == 'WFH':
            stats['wfh'] += 1
        elif s in ['SL', 'SICK LEAVE', 'LEAVE', 'PLANNED LEAVE', 'PL']:
            stats['leave'] += 1
        elif s in ['INDIA HOLIDAY', 'HOLIDAY']:
            stats['holiday'] += 1
    
    working = stats['wfo'] + stats['wfh']
    stats['wfo_pct'] = round((stats['wfo'] / working * 100), 1) if working > 0 else 0
    stats['wfh_pct'] = round((stats['wfh'] / working * 100), 1) if working > 0 else 0
    stats['working'] = working
    
    return stats


@app.route('/')
def index():
    """Landing page with team summary"""
    data, meta = load_data()
    
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
        # Calculate WFO percentage based on working days
        stats['wfo_pct'] = round((stats['wfo'] / working_days * 100), 1) if working_days > 0 else 0
        admins.append({
            'name': emp['name'],
            'person_id': emp['person_id'],
            'stats': stats
        })
    
    # Team totals - based on working days
    total_wfo = sum(a['stats']['wfo'] for a in admins)
    num_members = len(admins)
    total_possible_wfo = working_days * num_members
    team_wfo_pct = round((total_wfo / total_possible_wfo * 100), 1) if total_possible_wfo > 0 else 0
    
    return render_template('index.html',
                         admins=admins,
                         month=month,
                         months=available_months,
                         team_wfo_pct=team_wfo_pct,
                         working_days=working_days,
                         wfo_target_days=CONFIG['wfo_target_days'],
                         meta=meta)


@app.route('/admin/<n>')
def admin_calendar(n):
    """Calendar view for specific admin"""
    data, meta = load_data()
    
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
    # Calculate WFO percentage based on working days
    stats['wfo_pct'] = round((stats['wfo'] / working_days * 100), 1) if working_days > 0 else 0
    
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
                         calendar_data=calendar_data,
                         month=month,
                         months=available_months,
                         working_days=working_days,
                         wfo_target_days=CONFIG['wfo_target_days'],
                         meta=meta)


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
