import os
import pandas as pd
from flask import Flask, request, render_template, jsonify, redirect, url_for, send_from_directory
from datetime import datetime
import json
from collections import defaultdict
import logging
import traceback
import glob

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

# Configuration
DATA_FOLDER = 'data'
EXCEL_FILE_PATTERN = '*.xlsx'

# Create data folder if it doesn't exist
os.makedirs(DATA_FOLDER, exist_ok=True)
# Create static folder if it doesn't exist
os.makedirs('static/images', exist_ok=True)

def find_latest_excel_file():
    """Find the latest Excel file in the data folder"""
    try:
        excel_files = glob.glob(os.path.join(DATA_FOLDER, EXCEL_FILE_PATTERN))
        
        if not excel_files:
            excel_files = glob.glob(EXCEL_FILE_PATTERN)
        
        if not excel_files:
            logger.warning("No Excel files found")
            return None
        
        latest_file = max(excel_files, key=os.path.getmtime)
        logger.info(f"Found latest Excel file: {latest_file}")
        
        file_stats = os.stat(latest_file)
        return {
            'filepath': latest_file,
            'filename': os.path.basename(latest_file),
            'size': file_stats.st_size,
            'modified': datetime.fromtimestamp(file_stats.st_mtime).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error finding Excel file: {e}")
        return None

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

def load_data_from_repo():
    """Load and process data from the repository Excel file"""
    try:
        file_info = find_latest_excel_file()
        
        if not file_info:
            return None, None, {}
        
        filepath = file_info['filepath']
        logger.info(f"Loading data from: {filepath}")
        
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
        
        metadata = {
            'source_file': file_info['filename'],
            'file_path': filepath,
            'file_size': file_info['size'],
            'last_modified': file_info['modified'],
            'total_sheets': len(combined_data),
            'total_employees': len(set(emp['name'] for sheet in combined_data for emp in sheet['employees'] if emp['name'] and emp['name'].strip() != 'Employee Name')) if combined_data else 0,
            'sheet_names': sorted_month_names,
            'loaded_timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Loaded data for {len(combined_data)} sheets, {metadata['total_employees']} employees")
        return combined_data, sorted_monthly_data, metadata
        
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return None, None, {}

@app.route('/api/raw-excel-debug')
def raw_excel_debug():
    """Debug endpoint to see raw Excel structure"""
    try:
        file_info = find_latest_excel_file()
        if not file_info:
            return jsonify({'status': 'no_file'}), 404
        
        filepath = file_info['filepath']
        
        # Read Excel file with minimal processing
        excel_data = pd.read_excel(filepath, sheet_name=None, header=None)
        
        debug_data = {}
        for sheet_name, df in excel_data.items():
            # Get first 10 rows and 10 columns for debugging
            sheet_debug = {
                'shape': df.shape,
                'raw_data': []
            }
            
            for i in range(min(10, len(df))):
                row_data = []
                for j in range(min(10, len(df.columns))):
                    cell_value = df.iloc[i, j]
                    row_data.append({
                        'value': str(cell_value) if pd.notna(cell_value) else 'NaN',
                        'type': str(type(cell_value).__name__)
                    })
                sheet_debug['raw_data'].append({
                    'row_index': i,
                    'data': row_data
                })
            
            debug_data[sheet_name] = sheet_debug
        
        return jsonify({
            'status': 'success',
            'file_info': file_info,
            'excel_debug': debug_data
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

def process_monthly_sheet(df, sheet_name):
    """Process a single monthly sheet and extract relevant data"""
    try:
        if df.empty or len(df) < 3:
            return None
        
        logger.info(f"=== PROCESSING SHEET: {sheet_name} ===")
        logger.info(f"Sheet shape: {df.shape}")
        
        # Print the first 10 rows to understand structure
        logger.info("First 10 rows of the sheet:")
        for i in range(min(10, len(df))):
            row_data = []
            for j in range(min(8, len(df.columns))):
                cell_value = df.iloc[i, j]
                row_data.append(str(cell_value) if pd.notna(cell_value) else 'NaN')
            logger.info(f"Row {i}: {row_data}")
        
        employee_data = []
        date_columns = []
        
        # Find date columns (they start from column 5 onwards)
        for col_idx, col_name in enumerate(df.columns):
            if col_idx >= 5:
                date_columns.append(str(col_name))
        
        logger.info(f"Found {len(date_columns)} date columns: {date_columns[:5]}...")
        
        # FIXED: Use sheet-specific seen_employees to avoid cross-sheet conflicts
        seen_employees = set()
        
        # Process ALL rows starting from index 2 (row 3 in Excel)
        for idx in range(2, len(df)):
            try:
                row = df.iloc[idx]
                
                # Get employee name from first column
                emp_name_raw = row.iloc[0]
                if pd.isna(emp_name_raw):
                    logger.info(f"Row {idx}: Skipping - empty name")
                    continue
                    
                emp_name = str(emp_name_raw).strip()
                
                # Enhanced debug for ALL employees
                logger.info(f"\n--- PROCESSING ROW {idx} (Excel row {idx+1}) ---")
                logger.info(f"Employee Name: '{emp_name}'")
                logger.info(f"Person ID: '{row.iloc[1] if pd.notna(row.iloc[1]) else 'NaN'}'")
                logger.info(f"Department: '{row.iloc[2] if pd.notna(row.iloc[2]) else 'NaN'}'")
                logger.info(f"Team Manager: '{row.iloc[3] if pd.notna(row.iloc[3]) else 'NaN'}'")
                logger.info(f"Shift Timings: '{row.iloc[4] if pd.notna(row.iloc[4]) else 'NaN'}'")
                
                # FIXED: More lenient name validation
                if (not emp_name or 
                    emp_name == '' or 
                    emp_name.lower() == 'employee name' or
                    emp_name.lower() == 'nan' or
                    len(emp_name.strip()) == 0):
                    logger.info(f"Skipping invalid name: '{emp_name}'")
                    continue
                
                # FIXED: Check for duplicates within this sheet only
                if emp_name in seen_employees:
                    logger.info(f"Skipping duplicate employee in this sheet: {emp_name}")
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
                logger.info(f"Extracting daily statuses for {emp_name}:")
                
                for col_idx, date_col in enumerate(date_columns):
                    data_col_idx = col_idx + 5  # Date columns start at index 5
                    if data_col_idx < len(row):
                        status = row.iloc[data_col_idx]
                        if pd.notna(status):
                            clean_status = str(status).strip()
                            if clean_status and clean_status != 'nan' and clean_status != '':
                                employee_info['daily_status'][str(date_col)] = clean_status
                                status_count += 1
                                
                                # Log first 10 statuses for debugging
                                if status_count <= 10:
                                    logger.info(f"  {date_col}: '{clean_status}'")
                
                logger.info(f"Total statuses for {emp_name}: {status_count}")
                
                # FIXED: More lenient acceptance criteria - accept if they have either status data OR basic info
                if employee_info['name'] and (status_count > 0 or employee_info['department'] or employee_info['person_id']):
                    employee_data.append(employee_info)
                    logger.info(f"✅ ADDED: {emp_name} with {status_count} status entries")
                    
                    # SPECIAL DEBUG FOR LOKESH
                    if 'lokesh' in emp_name.lower():
                        logger.info(f"🔍 LOKESH SPECIAL DEBUG:")
                        logger.info(f"   Name: '{emp_name}'")
                        logger.info(f"   Status count: {status_count}")
                        logger.info(f"   Department: '{employee_info['department']}'")
                        logger.info(f"   Person ID: '{employee_info['person_id']}'")
                        logger.info(f"   Sample statuses: {dict(list(employee_info['daily_status'].items())[:3])}")
                else:
                    logger.info(f"❌ SKIPPED: {emp_name} - no valid data (status_count={status_count}, dept='{employee_info['department']}', id='{employee_info['person_id']}')")
                    
            except Exception as row_error:
                logger.error(f"Error processing row {idx}: {row_error}")
                continue
        
        logger.info(f"\n=== FINAL RESULT FOR {sheet_name} ===")
        logger.info(f"Total employees processed: {len(employee_data)}")
        for emp in employee_data:
            logger.info(f"  - {emp['name']}: {len(emp['daily_status'])} status entries")
        
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
    
    logger.info(f"Calculating stats for {employee['name']}, daily_status entries: {len(employee['daily_status'])}")
    
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
            elif status_upper in ['LEAVE', 'PLANNED LEAVE', 'PL']:  # Added PL here
                stats['planned_leave_days'] += 1
            elif status_upper in ['INDIA HOLIDAY', 'HOLIDAY']:
                stats['holiday_days'] += 1
            else:
                # Log unknown statuses for debugging
                logger.info(f"Unknown status for {employee['name']}: '{status}' (upper: '{status_upper}')")
    
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
    
    logger.info(f"Stats for {employee['name']}: WFO={stats['wfo_days']}, WFH={stats['wfh_days']}, SL={stats['sick_leave_days']}, PL={stats['planned_leave_days']}, Total={stats['total_days']}")
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
            elif status_upper in ['LEAVE', 'PLANNED LEAVE', 'PL']:  # Added PL here
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
    
    logger.info(f"Monthly summary: WFO={total_wfo}, WFH={total_wfh}, SL={total_sick_leave}, PL={total_planned_leave}, Holiday={total_holiday}")
    return summary

@app.route('/')
def index():
    """Minimal employee-focused landing page"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        if not combined_data:
            return render_template('no_data.html')
        
        # Get current month - DEFAULT TO LATEST (LAST) MONTH
        current_month = request.args.get('month')
        available_months = list(monthly_data.keys())
        
        if not current_month or current_month not in monthly_data:
            current_month = available_months[-1] if available_months else None
        
        if not current_month:
            return render_template('no_data.html')
        
        month_data = monthly_data[current_month]
        
        # FIXED: Filter out invalid employees and remove duplicates more carefully
        valid_employees = []
        seen_names = set()
        
        for employee in month_data['employees']:
            emp_name = employee['name'].strip()
            
            # FIXED: More careful validation
            if (not emp_name or 
                emp_name.lower() == 'employee name' or
                len(emp_name.strip()) == 0):
                logger.info(f"Filtering out invalid employee name: '{emp_name}'")
                continue
            
            # FIXED: Case-insensitive duplicate check
            emp_name_lower = emp_name.lower()
            if emp_name_lower in seen_names:
                logger.info(f"Filtering out duplicate employee: '{emp_name}'")
                continue
            
            seen_names.add(emp_name_lower)
            
            # Calculate stats
            stats = calculate_employee_stats(employee, month_data['date_columns'])
            employee_with_stats = employee.copy()
            employee_with_stats['stats'] = stats
            valid_employees.append(employee_with_stats)
            
            # SPECIAL LOG FOR LOKESH
            if 'lokesh' in emp_name.lower():
                logger.info(f"🔍 LOKESH IN FINAL LIST: {emp_name} with {len(employee['daily_status'])} statuses")
        
        # Calculate monthly summary
        monthly_summary = calculate_monthly_summary(month_data)
        
        # Get current month index for navigation
        current_month_index = available_months.index(current_month) if current_month in available_months else len(available_months) - 1
        
        logger.info(f"Displaying {len(valid_employees)} unique employees for month: {current_month}")
        
        # DEBUG: Log all employee names in final list
        logger.info("Final employee list:")
        for emp in valid_employees:
            logger.info(f"  - {emp['name']}")
        
        return render_template('minimal_dashboard.html',
                             employees=valid_employees,
                             current_month=current_month,
                             monthly_summary=monthly_summary,
                             available_months=available_months,
                             current_month_index=current_month_index,
                             metadata=metadata)
        
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return render_template('error.html', error_message=str(e))

@app.route('/calendar')
def calendar_view():
    """Excel-like calendar view"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        if not combined_data:
            return redirect(url_for('index'))
        
        # Get current month - DEFAULT TO LATEST MONTH
        current_month = request.args.get('month')
        available_months = list(monthly_data.keys())
        
        if not current_month or current_month not in monthly_data:
            current_month = available_months[-1] if available_months else None
        
        if not current_month:
            return redirect(url_for('index'))
        
        month_data = monthly_data[current_month]
        
        # FIXED: Filter out duplicate employees with case-insensitive checking
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
        
        # Update month_data with unique employees
        month_data_clean = month_data.copy()
        month_data_clean['employees'] = unique_employees
        
        # Calculate monthly statistics for calendar view
        monthly_stats = calculate_monthly_summary(month_data_clean)
        
        # Get navigation info
        current_month_index = available_months.index(current_month)
        can_go_previous = current_month_index > 0
        can_go_next = current_month_index < len(available_months) - 1
        
        logger.info(f"Calendar view: {len(unique_employees)} unique employees for month: {current_month}")
        
        return render_template('excel_calendar.html',
                             month_data=month_data_clean,
                             current_month=current_month,
                             monthly_stats=monthly_stats,
                             available_months=available_months,
                             current_month_index=current_month_index,
                             can_go_previous=can_go_previous,
                             can_go_next=can_go_next)
        
    except Exception as e:
        logger.error(f"Error in calendar route: {e}")
        return redirect(url_for('index'))

@app.route('/api/refresh')
def refresh_data():
    """API endpoint to refresh data from repository file"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        if combined_data:
            return jsonify({
                'status': 'success',
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
                'message': 'No Excel file found in repository'
            }), 404
            
    except Exception as e:
        logger.error(f"Error refreshing data: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/file-info')
def file_info():
    """API endpoint to get current file information"""
    try:
        file_info = find_latest_excel_file()
        if file_info:
            return jsonify({
                'status': 'success',
                'file_info': file_info
            })
        else:
            return jsonify({
                'status': 'no_file', 
                'message': 'No Excel file found'
            }), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/debug/<employee_name>')
def debug_employee_data(employee_name):
    """Debug endpoint to check specific employee data"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        if not combined_data:
            return jsonify({'status': 'no_data'}), 404
        
        debug_info = {
            'employee_name': employee_name,
            'found_in_sheets': [],
            'raw_data': {}
        }
        
        for sheet_data in combined_data:
            sheet_name = sheet_data['sheet_name']
            for employee in sheet_data['employees']:
                if employee['name'].lower() == employee_name.lower():
                    debug_info['found_in_sheets'].append(sheet_name)
                    debug_info['raw_data'][sheet_name] = {
                        'name': employee['name'],
                        'person_id': employee['person_id'],
                        'department': employee['department'],
                        'team_manager': employee['team_manager'],
                        'shift_timings': employee['shift_timings'],
                        'daily_status_count': len(employee['daily_status']),
                        'daily_status_sample': dict(list(employee['daily_status'].items())[:5]),
                        'all_daily_status': employee['daily_status']
                    }
        
        return jsonify({
            'status': 'success',
            'debug_info': debug_info
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        file_info = find_latest_excel_file()
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        # Add debug info about all employees
        employee_debug = {}
        if combined_data:
            for sheet_data in combined_data:
                sheet_name = sheet_data['sheet_name']
                employee_debug[sheet_name] = []
                for emp in sheet_data['employees']:
                    employee_debug[sheet_name].append({
                        'name': emp['name'],
                        'status_count': len(emp['daily_status'])
                    })
        
        return jsonify({
            'status': 'healthy', 
            'timestamp': datetime.now().isoformat(),
            'has_data_file': file_info is not None,
            'has_processed_data': combined_data is not None,
            'file_info': file_info,
            'data_info': metadata if combined_data else None,
            'employee_debug': employee_debug,
            'version': '2.1.1-lokesh-fix',
            'data_folder': DATA_FOLDER
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting WFO Tracker v2.1.1-lokesh-fix on port {port}")
    logger.info(f"Data folder: {DATA_FOLDER}")
    app.run(host='0.0.0.0', port=port, debug=False)
