from flask import Flask, render_template, request, jsonify
import pandas as pd
import os
from datetime import datetime, timedelta
import calendar

app = Flask(__name__)

# Global variable to store the master data
df = None

def load_master_data():
    """Load master data from CSV files in master_data directory"""
    global df
    master_data_dir = 'master_data'
    
    if not os.path.exists(master_data_dir):
        return None
    
    csv_files = [f for f in os.listdir(master_data_dir) if f.endswith('.csv')]
    
    if not csv_files:
        return None
    
    # Load and combine all CSV files
    all_data = []
    for file in csv_files:
        try:
            file_path = os.path.join(master_data_dir, file)
            temp_df = pd.read_csv(file_path)
            # Ensure consistent column names (strip whitespace)
            temp_df.columns = temp_df.columns.str.strip()
            all_data.append(temp_df)
        except Exception as e:
            print(f"Error loading {file}: {e}")
            continue
    
    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        # Convert Date column to datetime
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            # Add month-year for easier grouping
            df['Month_Year'] = df['Date'].dt.strftime('%Y-%m')
            df['Month_Name'] = df['Date'].dt.strftime('%B %Y')
        return df
    
    return None

def get_employee_summary():
    """Get summary data for all employees"""
    if df is None:
        return {}
    
    # Get unique employees
    employees = df['Employee Name'].unique() if 'Employee Name' in df.columns else []
    
    summary_data = {}
    
    for employee in employees:
        emp_data = df[df['Employee Name'] == employee]
        
        # Current month stats
        current_month = datetime.now().strftime('%Y-%m')
        current_month_data = emp_data[emp_data['Month_Year'] == current_month]
        
        wfh_count = len(current_month_data[current_month_data['Type'] == 'WFH']) if 'Type' in df.columns else 0
        wfo_count = len(current_month_data[current_month_data['Type'] == 'WFO']) if 'Type' in df.columns else 0
        
        # Last 6 months data
        last_6_months = []
        for i in range(6):
            month_date = datetime.now() - timedelta(days=30*i)
            month_str = month_date.strftime('%Y-%m')
            month_data = emp_data[emp_data['Month_Year'] == month_str]
            
            month_wfh = len(month_data[month_data['Type'] == 'WFH']) if 'Type' in df.columns else 0
            month_wfo = len(month_data[month_data['Type'] == 'WFO']) if 'Type' in df.columns else 0
            
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
    
    # Group by month
    monthly_data = {}
    
    for month_year in emp_data['Month_Year'].unique():
        month_data = emp_data[emp_data['Month_Year'] == month_year]
        
        wfh_count = len(month_data[month_data['Type'] == 'WFH']) if 'Type' in df.columns else 0
        wfo_count = len(month_data[month_data['Type'] == 'WFO']) if 'Type' in df.columns else 0
        
        # Get individual dates
        dates_list = []
        for _, row in month_data.iterrows():
            dates_list.append({
                'date': row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else 'Unknown',
                'type': row['Type'] if 'Type' in row else 'Unknown',
                'day': row['Date'].strftime('%a') if pd.notna(row['Date']) else 'Unknown'
            })
        
        monthly_data[month_year] = {
            'month_name': month_data['Month_Name'].iloc[0] if len(month_data) > 0 else month_year,
            'wfh_count': wfh_count,
            'wfo_count': wfo_count,
            'total_days': wfh_count + wfo_count,
            'dates': sorted(dates_list, key=lambda x: x['date'])
        }
    
    return {
        'employee_name': employee_name,
        'monthly_breakdown': monthly_data
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
        return jsonify({'status': 'success', 'message': 'Data refreshed successfully'})
    else:
        return jsonify({'status': 'error', 'message': 'No data found'})

@app.route('/health')
def health_check():
    """Health check endpoint for Azure"""
    metadata = None
    if df is not None:
        metadata = {
            'total_records': len(df),
            'columns': df.columns.tolist(),
            'date_range': {
                'start': df['Date'].min().isoformat() if 'Date' in df.columns and df['Date'].notna().any() else None,
                'end': df['Date'].max().isoformat() if 'Date' in df.columns and df['Date'].notna().any() else None
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
