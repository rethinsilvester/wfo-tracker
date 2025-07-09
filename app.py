import os
import pandas as pd
from flask import Flask, request, render_template, jsonify, redirect, url_for, send_from_directory
from datetime import datetime
import json
import glob
import logging
from collections import defaultdict
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

# CONFIGURATION FIRST (so it's available to all functions)
TEAMS_CONFIG = {
    'uv-wcs': {
        'name': 'UV-WCS Admins',
        'display_name': 'UV-WCS Admin Team',
        'excel_pattern': 'App_Admin_UV-WCS*.xlsx',
        'data_folder': 'data/uv-wcs',
        'logo': '/static/images/Mouser_logo.png',
        'primary_color': '#667eea',
        'secondary_color': '#764ba2',
        'description': 'UV-WCS Administration Team Attendance Tracking',
        'wfo_target': 70,
        'team_id': 'uv-wcs'
    },
    'wcs-dev': {
        'name': 'WCS Developers',
        'display_name': 'WCS Development Team',
        'excel_pattern': 'WCS_DEV_tracker*.xlsx',
        'data_folder': 'data/wcs-dev',
        'logo': '/static/images/Developer_logo.png',
        'primary_color': '#28a745',
        'secondary_color': '#20c997',
        'description': 'WCS Development Team Attendance Tracking',
        'wfo_target': 60,
        'team_id': 'wcs-dev'
    }
}

GLOBAL_SETTINGS = {
    'app_title': 'WFO Tracker - Multi Team',
    'company_name': 'Your Company'
}

# Create data folders
for team_id, config in TEAMS_CONFIG.items():
    os.makedirs(config['data_folder'], exist_ok=True)

# HELPER FUNCTIONS (after config is defined)
def get_team_config(team_id):
    """Get team configuration or return None if invalid"""
    return TEAMS_CONFIG.get(team_id)

def sort_months_chronologically(month_names):
    """Sort month names in chronological order"""
    month_order = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'june': 6, 'july': 7, 'august': 8, 'september': 9,
        'october': 10, 'november': 11, 'december': 12
    }
    
    def get_month_number(month_name):
        words = month_name.lower().split()
        for word in words:
            if word in month_order:
                return month_order[word]
        return 0
    
    return sorted(month_names, key=get_month_number)

def find_latest_excel_file(team_id):
    """Find the latest Excel file for a specific team"""
    try:
        config = get_team_config(team_id)
        if not config:
            return None

        data_folder = config['data_folder']
        excel_pattern = config['excel_pattern']

        excel_files = glob.glob(os.path.join(data_folder, excel_pattern))

        if not excel_files:
            excel_files = glob.glob(os.path.join('data', excel_pattern))

        if not excel_files:
            logger.warning(f"No Excel files found for team {team_id}")
            return None

        latest_file = max(excel_files, key=os.path.getmtime)
        logger.info(f"Found latest Excel file for {team_id}: {latest_file}")

        file_stats = os.stat(latest_file)
        return {
            'filepath': latest_file,
            'filename': os.path.basename(latest_file),
            'size': file_stats.st_size,
            'modified': datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
            'team_id': team_id
        }

    except Exception as e:
        logger.error(f"Error finding Excel file for team {team_id}: {e}")
        return None

def process_monthly_sheet(df, sheet_name):
    """Process a single monthly sheet and extract relevant data"""
    try:
        if df.empty or len(df) < 3:
            return None
        
        logger.info(f"=== PROCESSING SHEET: {sheet_name} ===")
        logger.info(f"Sheet shape: {df.shape}")
        
        employee_data = []
        date_columns = []
        
        # Find date columns (they start from column 5 onwards)
        for col_idx, col_name in enumerate(df.columns):
            if col_idx >= 5:
                date_columns.append(str(col_name))
        
        logger.info(f"Found {len(date_columns)} date columns: {date_columns[:5]}...")
        
        # Use sheet-specific seen_employees to avoid cross-sheet conflicts
        seen_employees = set()
        
        # Process ALL rows starting from index 1 (row 2 in Excel)
        for idx in range(1, len(df)):
            try:
                row = df.iloc[idx]
                
                # Get employee name from first column
                emp_name_raw = row.iloc[0]
                if pd.isna(emp_name_raw):
                    continue
                    
                emp_name = str(emp_name_raw).strip()
                
                # More lenient name validation
                if (not emp_name or 
                    emp_name == '' or 
                    emp_name.lower() == 'employee name' or
                    emp_name.lower() == 'nan' or
                    len(emp_name.strip()) == 0):
                    continue
                
                # Check for duplicates within this sheet only
                if emp_name in seen_employees:
                    continue
                    
                seen_employees.add(emp_name)
                
                # Extract employee info with safe handling
                def safe_extract(col_idx):
                    if col_idx < len(row) and pd.notna(row.iloc[col_idx]):
                        value = str(row.iloc[col_idx]).strip()
                        return value if value != 'nan' else ''
                    return ''
                
                employee_info = {
                    'name': emp_name,
                    'person_id': safe_extract(1),
                    'department': safe_extract(2),
                    'team_manager': safe_extract(3),
                    'shift_timings': safe_extract(4),
                    'month': sheet_name,
                    'daily_status': {}
                }
                
                # Extract daily status
                status_count = 0
                
                for col_idx, date_col in enumerate(date_columns):
                    data_col_idx = col_idx + 5  # Date columns start at index 5
                    if data_col_idx < len(row):
                        status = row.iloc[data_col_idx]
                        
                        if pd.notna(status):
                            clean_status = str(status).strip()
                            if clean_status and clean_status != 'nan' and clean_status != '' and clean_status.upper() != 'NAN':
                                employee_info['daily_status'][str(date_col)] = clean_status
                                status_count += 1
                
                # Accept if they have either status data OR basic info
                if employee_info['name'] and (status_count > 0 or employee_info['department'] or employee_info['person_id']):
                    employee_data.append(employee_info)
                    logger.info(f"✅ ADDED: {emp_name} with {status_count} status entries")
                    
            except Exception as row_error:
                logger.error(f"Error processing row {idx}: {row_error}")
                continue
        
        logger.info(f"Total employees processed: {len(employee_data)}")
        
        return {
            'sheet_name': sheet_name,
            'employees': employee_data,
            'date_columns': date_columns
        }
        
    except Exception as e:
        logger.error(f"Error processing sheet {sheet_name}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

def calculate_employee_stats(employee, date_columns):
    """Calculate statistics for a single employee"""
    stats = {
        'wfo_days': 0,
        'wfh_days': 0,
        'sick_leave_days': 0,
        'planned_leave_days': 0,
        'holiday_days': 0,
        'total_days': 0
    }
    
    for date_col in date_columns:
        status = employee['daily_status'].get(str(date_col), '')
        if status and status.strip():
            stats['total_days'] += 1
            status_upper = status.upper().strip()
            
            if status_upper == 'WFO':
                stats['wfo_days'] += 1
            elif status_upper == 'WFH':
                stats['wfh_days'] += 1
            elif status_upper in ['SL', 'SICK LEAVE']:
                stats['sick_leave_days'] += 1
            elif status_upper in ['LEAVE', 'PLANNED LEAVE', 'PL']:
                stats['planned_leave_days'] += 1
            elif status_upper in ['INDIA HOLIDAY', 'HOLIDAY']:
                stats['holiday_days'] += 1
    
    # Calculate total leave days for backward compatibility
    stats['leave_days'] = stats['sick_leave_days'] + stats['planned_leave_days']
    
    # Calculate percentages
    if stats['total_days'] > 0:
        stats['wfo_percentage'] = round((stats['wfo_days'] / stats['total_days']) * 100, 1)
        stats['wfh_percentage'] = round((stats['wfh_days'] / stats['total_days']) * 100, 1)
        stats['sick_leave_percentage'] = round((stats['sick_leave_days'] / stats['total_days']) * 100, 1)
        stats['planned_leave_percentage'] = round((stats['planned_leave_days'] / stats['total_days']) * 100, 1)
        stats['leave_percentage'] = round((stats['leave_days'] / stats['total_days']) * 100, 1)
        stats['holiday_percentage'] = round((stats['holiday_days'] / stats['total_days']) * 100, 1)
        stats['attendance_rate'] = round(((stats['wfo_days'] + stats['wfh_days']) / stats['total_days']) * 100, 1)
    else:
        stats['wfo_percentage'] = 0
        stats['wfh_percentage'] = 0
        stats['sick_leave_percentage'] = 0
        stats['planned_leave_percentage'] = 0
        stats['leave_percentage'] = 0
        stats['holiday_percentage'] = 0
        stats['attendance_rate'] = 0
    
    return stats

def calculate_monthly_summary(month_data):
    """Calculate monthly summary statistics"""
    if not month_data or not month_data.get('employees'):
        return None
    
    total_wfo = total_wfh = total_sick_leave = total_planned_leave = total_holiday = total_working = 0
    
    for employee in month_data['employees']:
        for status in employee['daily_status'].values():
            status_upper = status.upper().strip()
            if status_upper == 'WFO':
                total_wfo += 1
                total_working += 1
            elif status_upper == 'WFH':
                total_wfh += 1
                total_working += 1
            elif status_upper in ['SL', 'SICK LEAVE']:
                total_sick_leave += 1
                total_working += 1
            elif status_upper in ['LEAVE', 'PLANNED LEAVE', 'PL']:
                total_planned_leave += 1
                total_working += 1
            elif status_upper in ['INDIA HOLIDAY', 'HOLIDAY']:
                total_holiday += 1
    
    total_leave = total_sick_leave + total_planned_leave
    
    summary = {
        'total_wfo_days': total_wfo,
        'total_wfh_days': total_wfh,
        'total_sick_leave_days': total_sick_leave,
        'total_planned_leave_days': total_planned_leave,
        'total_leave_days': total_leave,
        'total_holiday_days': total_holiday,
        'total_working_days': total_working,
        'total_employees': len(month_data['employees'])
    }
    
    if total_working > 0:
        summary['overall_wfo_percentage'] = round((total_wfo / total_working) * 100, 1)
        summary['overall_wfh_percentage'] = round((total_wfh / total_working) * 100, 1)
        summary['overall_sick_leave_percentage'] = round((total_sick_leave / total_working) * 100, 1)
        summary['overall_planned_leave_percentage'] = round((total_planned_leave / total_working) * 100, 1)
        summary['overall_leave_percentage'] = round((total_leave / total_working) * 100, 1)
    else:
        summary['overall_wfo_percentage'] = 0
        summary['overall_wfh_percentage'] = 0
        summary['overall_sick_leave_percentage'] = 0
        summary['overall_planned_leave_percentage'] = 0
        summary['overall_leave_percentage'] = 0
    
    return summary

def load_data_from_repo(team_id):
    """Load and process data for a specific team"""
    try:
        file_info = find_latest_excel_file(team_id)
        
        if not file_info:
            return None, None, {}
        
        filepath = file_info['filepath']
        logger.info(f"Loading data for team {team_id} from: {filepath}")
        
        excel_data = pd.read_excel(filepath, sheet_name=None)
        logger.info(f"Loaded Excel file with sheets: {list(excel_data.keys())}")
        
        combined_data = []
        monthly_data = {}
        
        for sheet_name, df in excel_data.items():
            if df.empty:
                continue
                
            processed_data = process_monthly_sheet(df, sheet_name)
            if processed_data is not None:
                combined_data.append(processed_data)
                monthly_data[sheet_name] = processed_data
        
        sorted_month_names = sort_months_chronologically(list(monthly_data.keys()))
        sorted_monthly_data = {month: monthly_data[month] for month in sorted_month_names}
        
        config = get_team_config(team_id)
        metadata = {
            'team_id': team_id,
            'team_name': config['name'],
            'team_display_name': config['display_name'],
            'source_file': file_info['filename'],
            'file_path': filepath,
            'file_size': file_info['size'],
            'last_modified': file_info['modified'],
            'total_sheets': len(combined_data),
            'total_employees': len(set(emp['name'] for sheet in combined_data for emp in sheet['employees'] if emp['name'] and emp['name'].strip() != 'Employee Name')) if combined_data else 0,
            'sheet_names': sorted_month_names,
            'loaded_timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Loaded data for team {team_id}: {len(combined_data)} sheets, {metadata['total_employees']} employees")
        return combined_data, sorted_monthly_data, metadata
        
    except Exception as e:
        logger.error(f"Error loading data for team {team_id}: {e}")
        return None, None, {}

# ROUTES
@app.route('/')
def landing():
    """Landing page with team selector"""
    return render_template('team_selector.html', teams=TEAMS_CONFIG, global_settings=GLOBAL_SETTINGS)

@app.route('/<team_id>/')
def team_dashboard(team_id):
    """Team-specific dashboard"""
    config = get_team_config(team_id)
    if not config:
        return redirect(url_for('landing'))
    
    try:
        combined_data, monthly_data, metadata = load_data_from_repo(team_id)
        
        if not combined_data:
            return render_template('no_data.html', team_config=config)
        
        # Get current month - DEFAULT TO LATEST (LAST) MONTH
        current_month = request.args.get('month')
        available_months = list(monthly_data.keys())
        
        if not current_month or current_month not in monthly_data:
            current_month = available_months[-1] if available_months else None
        
        if not current_month:
            return render_template('no_data.html', team_config=config)
        
        month_data = monthly_data[current_month]
        
        # Process employees
        valid_employees = []
        seen_names = set()
        
        for employee in month_data['employees']:
            emp_name = employee['name'].strip()
            
            if (not emp_name or 
                emp_name.lower() == 'employee name' or
                len(emp_name.strip()) == 0):
                continue
            
            emp_name_lower = emp_name.lower()
            if emp_name_lower in seen_names:
                continue
                
            seen_names.add(emp_name_lower)
            
            stats = calculate_employee_stats(employee, month_data['date_columns'])
            employee_with_stats = employee.copy()
            employee_with_stats['stats'] = stats
            valid_employees.append(employee_with_stats)
        
        monthly_summary = calculate_monthly_summary(month_data)
        current_month_index = available_months.index(current_month) if current_month in available_months else len(available_months) - 1
        
        logger.info(f"Displaying {len(valid_employees)} employees for team {team_id}, month: {current_month}")
        
        return render_template('minimal_dashboard.html',
                             employees=valid_employees,
                             current_month=current_month,
                             monthly_summary=monthly_summary,
                             available_months=available_months,
                             current_month_index=current_month_index,
                             metadata=metadata,
                             team_config=config)
        
    except Exception as e:
        logger.error(f"Error in team dashboard for {team_id}: {e}")
        return render_template('error.html', error_message=str(e), team_config=config)

@app.route('/<team_id>/calendar')
def team_calendar(team_id):
    """Team-specific calendar view"""
    config = get_team_config(team_id)
    if not config:
        return redirect(url_for('landing'))
    
    try:
        combined_data, monthly_data, metadata = load_data_from_repo(team_id)
        
        if not combined_data:
            return redirect(url_for('team_dashboard', team_id=team_id))
        
        # Get current month - DEFAULT TO LATEST MONTH
        current_month = request.args.get('month')
        available_months = list(monthly_data.keys())
        
        if not current_month or current_month not in monthly_data:
            current_month = available_months[-1] if available_months else None
        
        if not current_month:
            return redirect(url_for('team_dashboard', team_id=team_id))
        
        month_data = monthly_data[current_month]
        
        # Filter unique employees
        unique_employees = []
        seen_names = set()
        
        for employee in month_data['employees']:
            emp_name = employee['name'].strip()
            emp_name_lower = emp_name.lower()
            
            if (emp_name and 
                emp_name.lower() != 'employee name' and
                emp_name_lower not in seen_names):
                seen_names.add(emp_name_lower)
                unique_employees.append(employee)
        
        month_data_clean = month_data.copy()
        month_data_clean['employees'] = unique_employees
        
        monthly_stats = calculate_monthly_summary(month_data_clean)
        
        current_month_index = available_months.index(current_month)
        can_go_previous = current_month_index > 0
        can_go_next = current_month_index < len(available_months) - 1
        
        logger.info(f"Calendar view for team {team_id}: {len(unique_employees)} employees, month: {current_month}")
        
        return render_template('excel_calendar.html',
                             month_data=month_data_clean,
                             current_month=current_month,
                             monthly_stats=monthly_stats,
                             available_months=available_months,
                             current_month_index=current_month_index,
                             can_go_previous=can_go_previous,
                             can_go_next=can_go_next,
                             team_config=config,
                             team_id=team_id)
        
    except Exception as e:
        logger.error(f"Error in team calendar for {team_id}: {e}")
        return redirect(url_for('team_dashboard', team_id=team_id))

@app.route('/api/<team_id>/refresh')
def refresh_team_data(team_id):
    """API endpoint to refresh data for a specific team"""
    config = get_team_config(team_id)
    if not config:
        return jsonify({'status': 'error', 'message': 'Invalid team'}), 400

    try:
        combined_data, monthly_data, metadata = load_data_from_repo(team_id)
        
        if combined_data:
            return jsonify({
                'status': 'success',
                'team_id': team_id,
                'team_name': config['name'],
                'total_employees': metadata.get('total_employees', 0),
                'total_sheets': metadata.get('total_sheets', 0),
                'last_modified': metadata.get('last_modified', 'Unknown'),
                'source_file': metadata.get('source_file', 'Unknown'),
                'available_months': metadata.get('sheet_names', []),
                'latest_month': metadata.get('sheet_names', [])[-1] if metadata.get('sheet_names') else None,
                'refreshed_at': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'status': 'no_data', 
                'message': f'No Excel file found for team {team_id}',
                'team_id': team_id
            }), 404
            
    except Exception as e:
        logger.error(f"Error refreshing data for team {team_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e), 'team_id': team_id}), 500

@app.route('/api/<team_id>/file-info')
def team_file_info(team_id):
    """API endpoint to get file information for a specific team"""
    config = get_team_config(team_id)
    if not config:
        return jsonify({'status': 'error', 'message': 'Invalid team'}), 400
    
    try:
        file_info = find_latest_excel_file(team_id)
        if file_info:
            return jsonify({
                'status': 'success',
                'team_id': team_id,
                'file_info': file_info
            })
        else:
            return jsonify({
                'status': 'no_file', 
                'message': f'No Excel file found for team {team_id}',
                'team_id': team_id
            }), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'team_id': team_id}), 500

@app.route('/health')
def health_check():
    """Enhanced health check with team information"""
    try:
        health_data = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '3.0.0-complete',
            'configuration': {
                'teams_count': len(TEAMS_CONFIG),
                'global_settings': GLOBAL_SETTINGS
            },
            'teams': {}
        }
        
        for team_id, config in TEAMS_CONFIG.items():
            file_info = find_latest_excel_file(team_id)
            combined_data, monthly_data, metadata = load_data_from_repo(team_id)
            
            health_data['teams'][team_id] = {
                'name': config['name'],
                'display_name': config['display_name'],
                'has_data_file': file_info is not None,
                'has_processed_data': combined_data is not None,
                'data_folder': config['data_folder'],
                'excel_pattern': config['excel_pattern'],
                'file_info': file_info,
                'data_info': metadata if combined_data else None
            }
        
        return jsonify(health_data)
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/debug/routes')
def debug_routes():
    """Debug routes"""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'route': rule.rule,
            'endpoint': rule.endpoint,
            'methods': list(rule.methods)
        })
    return jsonify(routes)

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Complete Multi-Team WFO Tracker on port {port}")
    logger.info(f"Configured teams: {list(TEAMS_CONFIG.keys())}")
    app.run(host='0.0.0.0', port=port, debug=False)
