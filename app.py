import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.utils
from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename
import io
import base64
from datetime import datetime, timedelta
import json
import calendar
from collections import defaultdict
import numpy as np

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

# Configuration
UPLOAD_FOLDER = 'uploads'
MASTER_DATA_FOLDER = 'master_data'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
MAX_FILE_SIZE = 32 * 1024 * 1024  # 32MB

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(MASTER_DATA_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# WFO Status mapping and colors
WFO_STATUS_CONFIG = {
    'WFO': {'color': '#28a745', 'label': 'Work From Office', 'icon': '🏢'},
    'WFH': {'color': '#007bff', 'label': 'Work From Home', 'icon': '🏠'},
    'SL': {'color': '#dc3545', 'label': 'Sick Leave', 'icon': '🤒'},
    'India Holiday': {'color': '#6c757d', 'label': 'Holiday', 'icon': '🎉'},
    'Leave': {'color': '#ffc107', 'label': 'Leave', 'icon': '🌴'},
    '': {'color': '#f8f9fa', 'label': 'No Data', 'icon': '❓'},
    None: {'color': '#f8f9fa', 'label': 'No Data', 'icon': '❓'}
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_master_data():
    """Load and process the latest master data from Excel file"""
    master_file_path = os.path.join(MASTER_DATA_FOLDER, 'master_data.xlsx')
    metadata_path = os.path.join(MASTER_DATA_FOLDER, 'metadata.json')
    
    if os.path.exists(master_file_path):
        try:
            # Read all sheets from the Excel file
            excel_data = pd.read_excel(master_file_path, sheet_name=None)
            
            # Process each sheet and combine data
            combined_data = []
            monthly_data = {}
            
            for sheet_name, df in excel_data.items():
                if df.empty:
                    continue
                    
                # Process the sheet data
                processed_data = process_monthly_sheet(df, sheet_name)
                if processed_data is not None:
                    combined_data.append(processed_data)
                    monthly_data[sheet_name] = processed_data
            
            # Load metadata if exists
            metadata = {}
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
            
            return combined_data, monthly_data, metadata
            
        except Exception as e:
            print(f"Error loading master data: {e}")
            return None, None, {}
    
    return None, None, {}

def process_monthly_sheet(df, sheet_name):
    """Process a single monthly sheet and extract relevant data"""
    try:
        if df.empty or len(df) < 2:
            return None
            
        # The first row contains headers, second row contains day names
        # Employee data starts from the third row
        
        # Extract employee data (starting from row 2, index 2)
        employee_data = []
        date_columns = []
        
        # Find date columns (they start from column 5 onwards)
        for col_idx, col_name in enumerate(df.columns):
            if col_idx >= 5:  # Skip first 5 columns (employee info)
                date_columns.append(col_name)
        
        # Process each employee row
        for idx, row in df.iterrows():
            if idx < 2:  # Skip header rows
                continue
                
            if pd.isna(row.iloc[0]):  # Skip empty rows
                continue
                
            employee_info = {
                'name': row.iloc[0],
                'person_id': row.iloc[1],
                'department': row.iloc[2],
                'team_manager': row.iloc[3],
                'shift_timings': row.iloc[4],
                'month': sheet_name,
                'daily_status': {}
            }
            
            # Extract daily status
            for col_idx, date_col in enumerate(date_columns):
                if col_idx + 5 < len(row):
                    status = row.iloc[col_idx + 5]
                    if pd.notna(status) and status != '':
                        employee_info['daily_status'][date_col] = status
            
            employee_data.append(employee_info)
        
        return {
            'sheet_name': sheet_name,
            'employees': employee_data,
            'date_columns': date_columns
        }
        
    except Exception as e:
        print(f"Error processing sheet {sheet_name}: {e}")
        return None

def save_master_data(file_path, filename):
    """Save uploaded file as master data"""
    master_file_path = os.path.join(MASTER_DATA_FOLDER, 'master_data.xlsx')
    metadata_path = os.path.join(MASTER_DATA_FOLDER, 'metadata.json')
    
    try:
        # Copy the uploaded file to master data location
        import shutil
        shutil.copy2(file_path, master_file_path)
        
        # Process the data to get statistics
        combined_data, monthly_data, _ = load_master_data()
        
        # Calculate statistics
        total_employees = 0
        total_sheets = 0
        if combined_data:
            total_sheets = len(combined_data)
            total_employees = len(set(emp['name'] for sheet in combined_data for emp in sheet['employees']))
        
        # Save metadata
        metadata = {
            'original_filename': filename,
            'upload_timestamp': datetime.now().isoformat(),
            'total_sheets': total_sheets,
            'total_employees': total_employees,
            'sheet_names': list(monthly_data.keys()) if monthly_data else []
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        return True
        
    except Exception as e:
        print(f"Error saving master data: {e}")
        return False

def calculate_wfo_analytics(combined_data):
    """Calculate WFO analytics from combined data"""
    if not combined_data:
        return {}
    
    analytics = {
        'overall_stats': {},
        'employee_stats': {},
        'department_stats': {},
        'monthly_trends': {},
        'team_stats': {}
    }
    
    # Initialize counters
    total_days = 0
    status_counts = defaultdict(int)
    employee_status_counts = defaultdict(lambda: defaultdict(int))
    department_status_counts = defaultdict(lambda: defaultdict(int))
    team_status_counts = defaultdict(lambda: defaultdict(int))
    monthly_status_counts = defaultdict(lambda: defaultdict(int))
    
    # Process all data
    for sheet_data in combined_data:
        month = sheet_data['sheet_name']
        for employee in sheet_data['employees']:
            emp_name = employee['name']
            dept = employee['department']
            team_manager = employee['team_manager']
            
            for date, status in employee['daily_status'].items():
                if status and status.strip():  # Only count non-empty statuses
                    total_days += 1
                    status_counts[status] += 1
                    employee_status_counts[emp_name][status] += 1
                    department_status_counts[dept][status] += 1
                    team_status_counts[team_manager][status] += 1
                    monthly_status_counts[month][status] += 1
    
    # Calculate overall statistics
    if total_days > 0:
        analytics['overall_stats'] = {
            'total_days': total_days,
            'wfo_percentage': round((status_counts['WFO'] / total_days) * 100, 1),
            'wfh_percentage': round((status_counts['WFH'] / total_days) * 100, 1),
            'leave_percentage': round((status_counts['SL'] / total_days) * 100, 1),
            'holiday_percentage': round((status_counts['India Holiday'] / total_days) * 100, 1),
            'status_distribution': dict(status_counts)
        }
    
    # Calculate employee statistics
    for emp_name, emp_status_counts in employee_status_counts.items():
        emp_total = sum(emp_status_counts.values())
        if emp_total > 0:
            analytics['employee_stats'][emp_name] = {
                'total_days': emp_total,
                'wfo_percentage': round((emp_status_counts['WFO'] / emp_total) * 100, 1),
                'wfh_percentage': round((emp_status_counts['WFH'] / emp_total) * 100, 1),
                'status_distribution': dict(emp_status_counts)
            }
    
    # Calculate department statistics
    for dept, dept_status_counts in department_status_counts.items():
        dept_total = sum(dept_status_counts.values())
        if dept_total > 0:
            analytics['department_stats'][dept] = {
                'total_days': dept_total,
                'wfo_percentage': round((dept_status_counts['WFO'] / dept_total) * 100, 1),
                'wfh_percentage': round((dept_status_counts['WFH'] / dept_total) * 100, 1),
                'status_distribution': dict(dept_status_counts)
            }
    
    # Calculate team statistics
    for team_manager, team_status_counts in team_status_counts.items():
        team_total = sum(team_status_counts.values())
        if team_total > 0:
            analytics['team_stats'][team_manager] = {
                'total_days': team_total,
                'wfo_percentage': round((team_status_counts['WFO'] / team_total) * 100, 1),
                'wfh_percentage': round((team_status_counts['WFH'] / team_total) * 100, 1),
                'status_distribution': dict(team_status_counts)
            }
    
    # Calculate monthly trends
    for month, month_status_counts in monthly_status_counts.items():
        month_total = sum(month_status_counts.values())
        if month_total > 0:
            analytics['monthly_trends'][month] = {
                'total_days': month_total,
                'wfo_percentage': round((month_status_counts['WFO'] / month_total) * 100, 1),
                'wfh_percentage': round((month_status_counts['WFH'] / month_total) * 100, 1),
                'status_distribution': dict(month_status_counts)
            }
    
    return analytics

def create_interactive_visualizations(analytics):
    """Create interactive visualizations using Plotly"""
    plots = []
    
    if not analytics or not analytics.get('overall_stats'):
        return plots
    
    try:
        # 1. Overall Status Distribution Pie Chart
        status_dist = analytics['overall_stats']['status_distribution']
        if status_dist:
            fig = go.Figure(data=[go.Pie(
                labels=list(status_dist.keys()),
                values=list(status_dist.values()),
                hole=0.3,
                marker_colors=[WFO_STATUS_CONFIG.get(status, {}).get('color', '#cccccc') for status in status_dist.keys()]
            )])
            fig.update_layout(
                title="Overall Work Status Distribution",
                font=dict(size=14),
                showlegend=True,
                height=400
            )
            plots.append(('Overall Status Distribution', fig.to_html(include_plotlyjs='cdn')))
        
        # 2. Monthly Trends Line Chart
        monthly_trends = analytics.get('monthly_trends', {})
        if monthly_trends:
            months = list(monthly_trends.keys())
            wfo_percentages = [monthly_trends[month]['wfo_percentage'] for month in months]
            wfh_percentages = [monthly_trends[month]['wfh_percentage'] for month in months]
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=months, y=wfo_percentages,
                mode='lines+markers',
                name='WFO %',
                line=dict(color='#28a745', width=3),
                marker=dict(size=8)
            ))
            fig.add_trace(go.Scatter(
                x=months, y=wfh_percentages,
                mode='lines+markers',
                name='WFH %',
                line=dict(color='#007bff', width=3),
                marker=dict(size=8)
            ))
            
            fig.update_layout(
                title="Monthly WFO vs WFH Trends",
                xaxis_title="Month",
                yaxis_title="Percentage (%)",
                height=400,
                hovermode='x unified'
            )
            plots.append(('Monthly Trends', fig.to_html(include_plotlyjs='cdn')))
        
        # 3. Department Comparison Bar Chart
        dept_stats = analytics.get('department_stats', {})
        if dept_stats:
            departments = list(dept_stats.keys())
            wfo_percentages = [dept_stats[dept]['wfo_percentage'] for dept in departments]
            wfh_percentages = [dept_stats[dept]['wfh_percentage'] for dept in departments]
            
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=departments, y=wfo_percentages,
                name='WFO %',
                marker_color='#28a745'
            ))
            fig.add_trace(go.Bar(
                x=departments, y=wfh_percentages,
                name='WFH %',
                marker_color='#007bff'
            ))
            
            fig.update_layout(
                title="Department-wise WFO vs WFH Comparison",
                xaxis_title="Department",
                yaxis_title="Percentage (%)",
                barmode='group',
                height=400
            )
            plots.append(('Department Comparison', fig.to_html(include_plotlyjs='cdn')))
        
        # 4. Employee Performance Heatmap
        emp_stats = analytics.get('employee_stats', {})
        if emp_stats and len(emp_stats) > 1:
            employees = list(emp_stats.keys())[:10]  # Show top 10 employees
            wfo_percentages = [emp_stats[emp]['wfo_percentage'] for emp in employees]
            
            fig = go.Figure(data=go.Heatmap(
                z=[wfo_percentages],
                x=employees,
                y=['WFO %'],
                colorscale='RdYlGn',
                showscale=True,
                hoverongaps=False
            ))
            
            fig.update_layout(
                title="Employee WFO Percentage Heatmap",
                xaxis_title="Employee",
                height=200,
                xaxis=dict(tickangle=45)
            )
            plots.append(('Employee Heatmap', fig.to_html(include_plotlyjs='cdn')))
        
        # 5. Team Manager Performance
        team_stats = analytics.get('team_stats', {})
        if team_stats:
            teams = list(team_stats.keys())
            wfo_percentages = [team_stats[team]['wfo_percentage'] for team in teams]
            
            fig = go.Figure(data=[go.Bar(
                x=teams,
                y=wfo_percentages,
                marker_color='#17a2b8',
                text=[f"{val}%" for val in wfo_percentages],
                textposition='auto'
            )])
            
            fig.update_layout(
                title="Team Manager-wise WFO Percentage",
                xaxis_title="Team Manager",
                yaxis_title="WFO Percentage (%)",
                height=400,
                xaxis=dict(tickangle=45)
            )
            plots.append(('Team Performance', fig.to_html(include_plotlyjs='cdn')))
        
    except Exception as e:
        print(f"Error creating visualizations: {e}")
    
    return plots

@app.route('/')
def index():
    """Main dashboard page"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if combined_data:
        # Calculate analytics
        analytics = calculate_wfo_analytics(combined_data)
        
        # Create interactive visualizations
        plots = create_interactive_visualizations(analytics)
        
        # Get summary statistics
        summary_stats = analytics.get('overall_stats', {})
        
        return render_template('modern_dashboard.html',
                             analytics=analytics,
                             plots=plots,
                             metadata=metadata,
                             summary_stats=summary_stats,
                             monthly_data=monthly_data,
                             show_upload_new=True)
    else:
        # No master data exists, show upload form
        return render_template('upload_form.html', no_data=True)

@app.route('/upload')
def upload_form():
    """Show upload form"""
    return render_template('upload_form.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and processing"""
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Save as master data
            if save_master_data(filepath, file.filename):
                flash('File uploaded successfully and set as master data!', 'success')
            else:
                flash('File uploaded but failed to set as master data', 'error')
            
            return redirect(url_for('index'))
                                 
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'error')
            return redirect(url_for('upload_form'))
    
    flash('Invalid file type. Please upload an Excel file (.xlsx or .xls)', 'error')
    return redirect(url_for('upload_form'))

@app.route('/api/analytics')
def get_analytics():
    """API endpoint to get analytics data"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if combined_data:
        analytics = calculate_wfo_analytics(combined_data)
        return jsonify({
            'status': 'success',
            'analytics': analytics,
            'metadata': metadata
        })
    else:
        return jsonify({'status': 'no_data'}), 404

@app.route('/api/employee/<employee_name>')
def get_employee_details(employee_name):
    """API endpoint to get specific employee details"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if not combined_data:
        return jsonify({'status': 'no_data'}), 404
    
    employee_data = []
    for sheet_data in combined_data:
        for employee in sheet_data['employees']:
            if employee['name'].lower() == employee_name.lower():
                employee_data.append({
                    'month': sheet_data['sheet_name'],
                    'employee_info': employee
                })
    
    if employee_data:
        return jsonify({
            'status': 'success',
            'employee_data': employee_data
        })
    else:
        return jsonify({'status': 'employee_not_found'}), 404

@app.route('/api/department/<department_name>')
def get_department_details(department_name):
    """API endpoint to get department-specific data"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if not combined_data:
        return jsonify({'status': 'no_data'}), 404
    
    department_employees = []
    for sheet_data in combined_data:
        for employee in sheet_data['employees']:
            if employee['department'].lower() == department_name.lower():
                department_employees.append({
                    'month': sheet_data['sheet_name'],
                    'employee_info': employee
                })
    
    if department_employees:
        return jsonify({
            'status': 'success',
            'department_data': department_employees
        })
    else:
        return jsonify({'status': 'department_not_found'}), 404

@app.route('/calendar')
def calendar_view():
    """Calendar view page"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if not combined_data:
        return redirect(url_for('index'))
    
    # Get current month or first available month
    current_month = request.args.get('month')
    if not current_month or current_month not in monthly_data:
        current_month = list(monthly_data.keys())[0]
    
    month_data = monthly_data[current_month]
    
    return render_template('calendar_view.html',
                         month_data=month_data,
                         current_month=current_month,
                         available_months=list(monthly_data.keys()),
                         wfo_config=WFO_STATUS_CONFIG)

@app.route('/reports')
def reports_view():
    """Reports and analytics page"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if not combined_data:
        return redirect(url_for('index'))
    
    analytics = calculate_wfo_analytics(combined_data)
    
    return render_template('reports.html',
                         analytics=analytics,
                         metadata=metadata,
                         monthly_data=monthly_data)

@app.route('/export/csv')
def export_csv():
    """Export data as CSV"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if not combined_data:
        return jsonify({'status': 'no_data'}), 404
    
    # Create CSV data
    csv_data = []
    for sheet_data in combined_data:
        for employee in sheet_data['employees']:
            for date, status in employee['daily_status'].items():
                csv_data.append({
                    'Employee Name': employee['name'],
                    'Person ID': employee['person_id'],
                    'Department': employee['department'],
                    'Team Manager': employee['team_manager'],
                    'Shift Timings': employee['shift_timings'],
                    'Month': sheet_data['sheet_name'],
                    'Date': date,
                    'Status': status
                })
    
    if csv_data:
        df = pd.DataFrame(csv_data)
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=wfo_data_export.csv'}
        )
    
    return jsonify({'status': 'no_data'}), 404

@app.route('/data/refresh')
def refresh_data():
    """API endpoint to refresh data from master file"""
    combined_data, monthly_data, metadata = load_master_data()
    
    if combined_data:
        analytics = calculate_wfo_analytics(combined_data)
        return jsonify({
            'status': 'success',
            'total_employees': len(set(emp['name'] for sheet in combined_data for emp in sheet['employees'])),
            'total_sheets': len(combined_data),
            'last_updated': metadata.get('upload_timestamp', 'Unknown'),
            'overall_stats': analytics.get('overall_stats', {})
        })
    else:
        return jsonify({'status': 'no_data'}), 404

@app.route('/health')
def health_check():
    """Health check endpoint"""
    combined_data, monthly_data, metadata = load_master_data()
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'has_master_data': combined_data is not None,
        'data_info': metadata if combined_data else None,
        'version': '2.0.0'
    })

if __name__ == '__main__':
    # Get port from environment variable (Azure sets this)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
