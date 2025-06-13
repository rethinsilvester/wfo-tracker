from flask import Flask, render_template, request, jsonify
import pandas as pd
import os
from datetime import datetime, timedelta
import calendar
import glob

app = Flask(__name__)

# Global variable to store the master data
df = None

def load_master_data():
    """Load master data from Excel files in master_data directory"""
    global df
    master_data_dir = 'master_data'
    
    if not os.path.exists(master_data_dir):
        return None
    
    # Find all Excel files in the directory
    excel_files = glob.glob(os.path.join(master_data_dir, '*.xlsx')) + glob.glob(os.path.join(master_data_dir, '*.xls'))
    
    if not excel_files:
        return None
    
    all_records = []
    
    for excel_file in excel_files:
        try:
            print(f"Loading Excel file: {excel_file}")
            
            # Read all sheets from the Excel file
            excel_data = pd.read_excel(excel_file, sheet_name=None)
            
            for sheet_name, sheet_df in excel_data.items():
                print(f"Processing sheet: {sheet_name}")
                
                # Clean column names (remove extra spaces)
                sheet_df.columns = sheet_df.columns.str.strip()
                
                # Find employee rows (skip header rows and empty rows)
                if 'Employee Name' in sheet_df.columns:
                    employee_rows = sheet_df[
                        sheet_df['Employee Name'].notna() & 
                        (sheet_df['Employee Name'] != 'Employee Name') &
                        (sheet_df['Employee Name'].astype(str).str.strip() != '')
                    ]
                else:
                    print(f"No 'Employee Name' column found in {sheet_name}")
                    continue
                
                for _, row in employee_rows.iterrows():
                    employee_name = str(row['Employee Name']).strip()
                    
                    # Skip if employee name is empty or invalid
                    if not employee_name or employee_name.lower() in ['nan', 'none', '']:
                        continue
                    
                    # Process each column that looks like a date
                    for col in sheet_df.columns:
                        col_str = str(col)
                        
                        # Check if column is a date (contains '/25' or is datetime)
                        is_date_column = False
                        formatted_date = None
                        
                        if '/25' in col_str or '/2025' in col_str:
                            try:
                                # Format like "2/3/25" or "2/3/2025"
                                if '/' in col_str:
                                    date_parts = col_str.split('/')
                                    if len(date_parts) >= 3:
                                        month = date_parts[0].zfill(2)
                                        day = date_parts[1].zfill(2)
                                        year = date_parts[2]
                                        if len(year) == 2:
                                            year = '20' + year
                                        formatted_date = f"{year}-{month}-{day}"
                                        is_date_column = True
                            except:
                                continue
                        elif isinstance(col, pd.Timestamp):
                            # If it's already a datetime object
                            formatted_date = col.strftime('%Y-%m-%d')
                            is_date_column = True
                        elif pd.notna(col):
                            try:
                                # Try to parse as date
                                parsed_date = pd.to_datetime(col)
                                formatted_date = parsed_date.strftime('%Y-%m-%d')
                                is_date_column = True
                            except:
                                continue
                        
                        if is_date_column and formatted_date:
                            work_type = row.get(col)
                            
                            # Only include WFH and WFO (skip SL, holidays, empty cells)
                            if work_type in ['WFH', 'WFO']:
                                record = {
                                    'Employee Name': employee_name,
                                    'Date': formatted_date,
                                    'Type': work_type,
                                    'Department': row.get('Department', 'IS'),
                                    'Team Manager': row.get('Team Manager', ''),
                                    'Shift Timings': row.get('Shift Timings', ''),
                                    'Source': f"{os.path.basename(excel_file)} - {sheet_name}"
                                }
                                all_records.append(record)
        
        except Exception as e:
            print(f"Error processing {excel_file}: {e}")
            continue
    
    if all_records:
        # Convert to DataFrame
        df = pd.DataFrame(all_records)
        
        # Convert Date column to datetime for easier processing
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        
        # Remove any rows with invalid dates
        df = df.dropna(subset=['Date'])
        
        # Add month-year for easier grouping
        df['Month_Year'] = df['Date'].dt.strftime('%Y-%m')
        df['Month_Name'] = df['Date'].dt.strftime('%B %Y')
        
        # Sort by employee and date
        df = df.sort_values(['Employee Name', 'Date']).reset_index(drop=True)
        
        print(f"Total records loaded: {len(df)}")
        print(f"Employees found: {df['Employee Name'].unique().tolist()}")
        
        return df
    
    return None

def get_employee_summary():
    """Get summary data for all employees"""
    if df is None:
        return {}
    
    # Get unique employees
    employees = df['Employee Name'].unique()
    
    summary_data = {}
    
    for employee in employees:
        emp_data = df[df['Employee Name'] == employee]
        
        # Current month stats
        current_month = datetime.now().strftime('%Y-%m')
        current_month_data = emp_data[emp_data['Month_Year'] == current_month]
        
        wfh_count = len(current_month_data[current_month_data['Type'] == 'WFH'])
        wfo_count = len(current_month_data[current_month_data['Type'] == 'WFO'])
        
        # Last 6 months data
        last_6_months = []
        for i in range(6):
            month_date = datetime.now() - timedelta(days=30*i)
            month_str = month_date.strftime('%Y-%m')
            month_data = emp_data[emp_data['Month_Year'] == month_str]
            
            month_wfh = len(month_data[month_data['Type'] == 'WFH'])
            month_wfo = len(month_data[month_data['Type'] == 'WFO'])
            
            last_6_months.append({
                'month': month_date.strftime('%B %Y'),
                'month_short': month_date.strftime('%b'),
                'wfh': month_wfh,
                'wfo': month_wfo,
                'total': month_wfh + month_wfo
            })
        
        summary_data[employee] = {
            'current_month_wfh': wfh_count,
            'current_month_wfo': wfo_count,
            'current_month_total': wfh_count + wfo_count,
            'last_6_months': list(reversed(last_6_months))  # Most recent first
        }
    
    return summary_data

def get_employee_details(employee_name):
    """Get detailed breakdown for a specific employee"""
    if df is None:
        return None
    
    emp_data = df[df['Employee Name'] == employee_name]
    
    if emp_data.empty:
        return None
    
    # Group by month
    monthly_data = {}
    
    for month_year in emp_data['Month_Year'].unique():
        month_data = emp_data[emp_data['Month_Year'] == month_year]
        
        wfh_count = len(month_data[month_data['Type'] == 'WFH'])
        wfo_count = len(month_data[month_data['Type'] == 'WFO'])
        
        # Get individual dates
        dates_list = []
        for _, row in month_data.iterrows():
            dates_list.append({
                'date': row['Date'].strftime('%Y-%m-%d'),
                'type': row['Type'],
                'day': row['Date'].strftime('%a'),
                'source': row.get('Source', 'Unknown')
            })
        
        monthly_data[month_year] = {
            'month_name': month_data['Month_Name'].iloc[0] if len(month_data) > 0 else month_year,
            'wfh_count': wfh_count,
            'wfo_count': wfo_count,
            'total_days': wfh_count + wfo_count,
            'dates': sorted(dates_list, key=lambda x: x['date'])
        }
    
    # Sort months by date (most recent first)
    sorted_monthly_data = dict(sorted(monthly_data.items(), key=lambda x: x[0], reverse=True))
    
    return {
        'employee_name': employee_name,
        'monthly_breakdown': sorted_monthly_data
    }

@app.route('/')
def home():
    """Main dashboard showing all employees"""
    global df
    df = load_master_data()
    
    if df is None:
        return render_template('no_data.html')
    
    employee_summary = get_employee_summary()
    
    return render_template('home.html', 
                         employees=employee_summary,
                         current_month=datetime.now().strftime('%B %Y'))

@app.route('/employee/<employee_name>')
def employee_details(employee_name):
    """Detailed view for a specific employee"""
    global df
    if df is None:
        df = load_master_data()
    
    if df is None:
        return render_template('no_data.html')
    
    employee_data = get_employee_details(employee_name)
    
    if employee_data is None:
        return render_template('no_data.html')
    
    return render_template('employee_details.html', employee_data=employee_data)

@app.route('/api/refresh')
def refresh_data():
    """API endpoint to refresh data"""
    global df
    df = load_master_data()
    
    if df is not None:
        employee_count = len(df['Employee Name'].unique())
        total_records = len(df)
        return jsonify({
            'status': 'success', 
            'message': f'Data refreshed successfully. Found {employee_count} employees with {total_records} records.'
        })
    else:
        return jsonify({'status': 'error', 'message': 'No Excel files found in master_data directory'})

@app.route('/api/data-info')
def data_info():
    """API endpoint to get data information"""
    if df is None:
        return jsonify({'status': 'error', 'message': 'No data loaded'})
    
    info = {
        'total_records': len(df),
        'employees': df['Employee Name'].unique().tolist(),
        'date_range': {
            'start': df['Date'].min().isoformat() if df['Date'].notna().any() else None,
            'end': df['Date'].max().isoformat() if df['Date'].notna().any() else None
        },
        'months_covered': sorted(df['Month_Year'].unique().tolist(), reverse=True),
        'data_sources': df['Source'].unique().tolist() if 'Source' in df.columns else []
    }
    
    return jsonify(info)

@app.route('/health')
def health_check():
    """Health check endpoint for Azure"""
    metadata = None
    if df is not None:
        metadata = {
            'total_records': len(df),
            'employees': df['Employee Name'].unique().tolist(),
            'date_range': {
                'start': df['Date'].min().isoformat() if df['Date'].notna().any() else None,
                'end': df['Date'].max().isoformat() if df['Date'].notna().any() else None
            }
        }
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'has_master_data': df is not None,
        'data_info': metadata if df is not None else None
    })

if __name__ == '__main__':
    # Get port from environment variable (Azure sets this to 80)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
