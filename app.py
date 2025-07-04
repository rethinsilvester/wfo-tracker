import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.utils
from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
import io
import base64
from datetime import datetime, timedelta
import json
import calendar
from collections import defaultdict
import numpy as np
import logging
import traceback
import glob

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

# Configuration - files will be read from repository
DATA_FOLDER = 'data'  # Folder in your repo containing Excel files
EXCEL_FILE_PATTERN = '*.xlsx'  # Pattern to match Excel files

# Create data folder if it doesn't exist (for local development)
os.makedirs(DATA_FOLDER, exist_ok=True)

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

def find_latest_excel_file():
    """Find the latest Excel file in the data folder"""
    try:
        # Look for Excel files in the data folder
        excel_files = glob.glob(os.path.join(DATA_FOLDER, EXCEL_FILE_PATTERN))
        
        if not excel_files:
            # Also check in root directory as fallback
            excel_files = glob.glob(EXCEL_FILE_PATTERN)
        
        if not excel_files:
            logger.warning("No Excel files found in data folder or root directory")
            return None
        
        # Sort by modification time, get the latest
        latest_file = max(excel_files, key=os.path.getmtime)
        logger.info(f"Found latest Excel file: {latest_file}")
        
        # Get file info
        file_stats = os.stat(latest_file)
        file_info = {
            'filepath': latest_file,
            'filename': os.path.basename(latest_file),
            'size': file_stats.st_size,
            'modified': datetime.fromtimestamp(file_stats.st_mtime).isoformat()
        }
        
        return file_info
        
    except Exception as e:
        logger.error(f"Error finding Excel file: {e}")
        return None

def load_data_from_repo():
    """Load and process data from the repository Excel file"""
    try:
        file_info = find_latest_excel_file()
        
        if not file_info:
            logger.warning("No Excel file found in repository")
            return None, None, {}
        
        filepath = file_info['filepath']
        logger.info(f"Loading data from: {filepath}")
        
        # Read all sheets from the Excel file
        excel_data = pd.read_excel(filepath, sheet_name=None)
        logger.info(f"Loaded Excel file with sheets: {list(excel_data.keys())}")
        
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
        
        # Create metadata
        metadata = {
            'source_file': file_info['filename'],
            'file_path': filepath,
            'file_size': file_info['size'],
            'last_modified': file_info['modified'],
            'total_sheets': len(combined_data),
            'total_employees': len(set(emp['name'] for sheet in combined_data for emp in sheet['employees'] if emp['name'])) if combined_data else 0,
            'sheet_names': list(monthly_data.keys()) if monthly_data else [],
            'loaded_timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Loaded data for {len(combined_data)} sheets, {metadata['total_employees']} employees")
        return combined_data, monthly_data, metadata
        
    except Exception as e:
        logger.error(f"Error loading data from repository: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None, None, {}

def process_monthly_sheet(df, sheet_name):
    """Process a single monthly sheet and extract relevant data"""
    try:
        if df.empty or len(df) < 2:
            logger.warning(f"Sheet {sheet_name} is empty or too small")
            return None
        
        logger.info(f"Processing sheet: {sheet_name} with {len(df)} rows and {len(df.columns)} columns")
        
        # Extract employee data (starting from row 2, index 2)
        employee_data = []
        date_columns = []
        
        # Find date columns (they start from column 5 onwards)
        for col_idx, col_name in enumerate(df.columns):
            if col_idx >= 5:  # Skip first 5 columns (employee info)
                date_columns.append(str(col_name))
        
        logger.info(f"Found {len(date_columns)} date columns in {sheet_name}")
        
        # Process each employee row
        employee_count = 0
        for idx, row in df.iterrows():
            if idx < 2:  # Skip header rows
                continue
                
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == '':  # Skip empty rows
                continue
                
            employee_info = {
                'name': str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else '',
                'person_id': str(row.iloc[1]) if pd.notna(row.iloc[1]) else '',
                'department': str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else '',
                'team_manager': str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else '',
                'shift_timings': str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else '',
                'month': sheet_name,
                'daily_status': {}
            }
            
            # Extract daily status
            for col_idx, date_col in enumerate(date_columns):
                if col_idx + 5 < len(row):
                    status = row.iloc[col_idx + 5]
                    if pd.notna(status) and str(status).strip() != '':
                        employee_info['daily_status'][str(date_col)] = str(status).strip()
            
            if employee_info['name']:  # Only add if name exists
                employee_data.append(employee_info)
                employee_count += 1
        
        logger.info(f"Processed sheet {sheet_name}: {employee_count} employees")
        return {
            'sheet_name': sheet_name,
            'employees': employee_data,
            'date_columns': date_columns
        }
        
    except Exception as e:
        logger.error(f"Error processing sheet {sheet_name}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

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
        if dept:  # Skip empty department names
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
        if team_manager:  # Skip empty team manager names
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
        
    except Exception as e:
        logger.error(f"Error creating visualizations: {e}")
    
    return plots

@app.route('/')
def index():
    """Main dashboard page"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
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
                                 show_refresh=True)  # Show refresh instead of upload
        else:
            return render_template('no_data.html')
            
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return render_template('error.html', error_message=str(e))

@app.route('/calendar')
def calendar_view():
    """Calendar view page"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
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
    except Exception as e:
        logger.error(f"Error in calendar route: {e}")
        return redirect(url_for('index'))

@app.route('/reports')
def reports_view():
    """Reports and analytics page"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        if not combined_data:
            return redirect(url_for('index'))
        
        analytics = calculate_wfo_analytics(combined_data)
        
        return render_template('reports.html',
                             analytics=analytics,
                             metadata=metadata,
                             monthly_data=monthly_data)
    except Exception as e:
        logger.error(f"Error in reports route: {e}")
        return redirect(url_for('index'))

@app.route('/api/refresh')
def refresh_data():
    """API endpoint to refresh data from repository file"""
    try:
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        if combined_data:
            analytics = calculate_wfo_analytics(combined_data)
            return jsonify({
                'status': 'success',
                'total_employees': metadata.get('total_employees', 0),
                'total_sheets': metadata.get('total_sheets', 0),
                'last_modified': metadata.get('last_modified', 'Unknown'),
                'source_file': metadata.get('source_file', 'Unknown'),
                'overall_stats': analytics.get('overall_stats', {}),
                'refreshed_at': datetime.now().isoformat()
            })
        else:
            return jsonify({'status': 'no_data', 'message': 'No Excel file found in repository'}), 404
            
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
            return jsonify({'status': 'no_file', 'message': 'No Excel file found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        file_info = find_latest_excel_file()
        combined_data, monthly_data, metadata = load_data_from_repo()
        
        return jsonify({
            'status': 'healthy', 
            'timestamp': datetime.now().isoformat(),
            'has_data_file': file_info is not None,
            'has_processed_data': combined_data is not None,
            'file_info': file_info,
            'data_info': metadata if combined_data else None,
            'version': '2.0.0-repo',
            'data_folder': DATA_FOLDER
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

if __name__ == '__main__':
    # Get port from environment variable (Azure sets this)
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask app on port {port}")
    logger.info(f"Data folder: {DATA_FOLDER}")
    logger.info(f"Excel file pattern: {EXCEL_FILE_PATTERN}")
    app.run(host='0.0.0.0', port=port, debug=False)
