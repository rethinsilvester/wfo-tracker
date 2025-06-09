import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
import io
import base64
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

# Configuration
MASTER_DATA_FOLDER = 'master_data'

# Create directories if they don't exist
os.makedirs(MASTER_DATA_FOLDER, exist_ok=True)

def load_master_data():
    """Load the latest master data if available"""
    master_file_path = os.path.join(MASTER_DATA_FOLDER, 'master_data.xlsx')
    metadata_path = os.path.join(MASTER_DATA_FOLDER, 'metadata.json')

    if os.path.exists(master_file_path):
        try:
            df = pd.read_excel(master_file_path)

            # Load metadata if exists
            metadata = {}
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)

            return df, metadata
        except Exception as e:
            print(f"Error loading master data: {e}")

    return None, {}

def process_attendance_data(df):
    """Process the Excel file and extract attendance data"""
    try:
        # Get all sheet names from the Excel file
        excel_file = pd.ExcelFile(io.BytesIO(df.to_excel(index=False).encode()))
        
        # If we have the actual file path, use it instead
        master_file_path = os.path.join(MASTER_DATA_FOLDER, 'master_data.xlsx')
        if os.path.exists(master_file_path):
            excel_file = pd.ExcelFile(master_file_path)
        
        all_data = {}
        
        for sheet_name in excel_file.sheet_names:
            print(f"Processing sheet: {sheet_name}")
            
            try:
                # Read the sheet
                sheet_df = pd.read_excel(excel_file, sheet_name=sheet_name)
                
                # Skip empty sheets
                if sheet_df.empty:
                    continue
                
                # Process attendance data
                processed_data = process_sheet_data(sheet_df, sheet_name)
                if processed_data:
                    all_data[sheet_name] = processed_data
                    
            except Exception as e:
                print(f"Error processing sheet {sheet_name}: {e}")
                continue
        
        return all_data
        
    except Exception as e:
        print(f"Error processing attendance data: {e}")
        return {}

def process_sheet_data(df, sheet_name):
    """Process individual sheet data"""
    try:
        # Clean column names
        df.columns = df.columns.astype(str).str.strip()
        
        # Look for employee name column (various possible names)
        name_column = None
        possible_name_columns = ['Employee Name', 'Name', 'Employee', 'person_name', 'Person Name']
        
        for col in df.columns:
            if any(name_col.lower() in col.lower() for name_col in possible_name_columns):
                name_column = col
                break
        
        if not name_column:
            print(f"No employee name column found in sheet {sheet_name}")
            return None
        
        # Get date columns (assume they start after the name column)
        name_col_index = df.columns.get_loc(name_column)
        date_columns = df.columns[name_col_index + 1:].tolist()
        
        # Remove any summary columns (like totals)
        date_columns = [col for col in date_columns if not any(
            summary_word in col.lower() 
            for summary_word in ['total', 'summary', 'count', 'wfo', 'wfh', 'sl', 'pl']
        )]
        
        employees = []
        dates = []
        
        # Process dates
        for col in date_columns:
            try:
                # Try to parse as date
                if isinstance(col, str) and col.strip():
                    # Extract date and day information
                    date_str = col.strip()
                    # Default day as empty, will be determined from context
                    day_str = ""
                    
                    dates.append({
                        'date': date_str,
                        'day': day_str
                    })
            except:
                continue
        
        # Process each employee
        for index, row in df.iterrows():
            try:
                employee_name = row[name_column]
                if pd.isna(employee_name) or str(employee_name).strip() == '':
                    continue
                
                employee_name = str(employee_name).strip()
                
                # Skip header rows or invalid entries
                if employee_name.lower() in ['employee name', 'name', 'employee', 'person name']:
                    continue
                
                attendance = []
                summary = {'WFO': 0, 'WFH': 0, 'SL': 0, 'PL': 0, 'Total_Days': 0}
                
                # Process attendance for each date
                for col in date_columns:
                    try:
                        value = row[col]
                        if pd.isna(value):
                            attendance.append('')
                        else:
                            status = str(value).strip().upper()
                            attendance.append(status)
                            
                            # Count attendance types
                            if status in summary:
                                summary[status] += 1
                            elif status == 'WFO':
                                summary['WFO'] += 1
                            elif status == 'WFH':
                                summary['WFH'] += 1
                            elif status == 'SL':
                                summary['SL'] += 1
                            elif status == 'PL':
                                summary['PL'] += 1
                    except:
                        attendance.append('')
                
                # Calculate total working days
                summary['Total_Days'] = len([a for a in attendance if a and a.strip()])
                
                employees.append({
                    'name': employee_name,
                    'person_id': f"EMP{index:03d}",
                    'department': 'IS',
                    'team_manager': 'Shivakumar Jayabalan',
                    'shift_timings': 'Standard',
                    'attendance': attendance,
                    'summary': summary
                })
                
            except Exception as e:
                print(f"Error processing employee row {index}: {e}")
                continue
        
        return {
            'employees': employees,
            'dates': dates,
            'sheet_name': sheet_name
        }
        
    except Exception as e:
        print(f"Error in process_sheet_data: {e}")
        return None

def create_visualizations(df):
    """Create visualizations from the dataframe"""
    plots = []

    try:
        # Set style
        plt.style.use('default')
        sns.set_palette("husl")

        # Get numeric columns
        numeric_columns = df.select_dtypes(include=['number']).columns.tolist()

        if len(numeric_columns) >= 2:
            # Correlation heatmap
            fig, ax = plt.subplots(figsize=(10, 8))
            correlation_matrix = df[numeric_columns].corr()
            sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', center=0, ax=ax)
            ax.set_title('Correlation Matrix of Numeric Variables')

            img = io.BytesIO()
            plt.savefig(img, format='png', bbox_inches='tight', dpi=300)
            img.seek(0)
            plot_url = base64.b64encode(img.getvalue()).decode()
            plots.append(('Correlation Matrix', plot_url))
            plt.close()

        # Distribution plots for first few numeric columns
        for i, col in enumerate(numeric_columns[:3]):
            if df[col].notna().sum() > 0:
                fig, ax = plt.subplots(figsize=(10, 6))
                df[col].hist(bins=30, alpha=0.7, ax=ax)
                ax.set_title(f'Distribution of {col}')
                ax.set_xlabel(col)
                ax.set_ylabel('Frequency')

                img = io.BytesIO()
                plt.savefig(img, format='png', bbox_inches='tight', dpi=300)
                img.seek(0)
                plot_url = base64.b64encode(img.getvalue()).decode()
                plots.append((f'Distribution: {col}', plot_url))
                plt.close()

        # If there are categorical columns, create a bar chart
        categorical_columns = df.select_dtypes(include=['object']).columns.tolist()
        for col in categorical_columns[:2]:  # First 2 categorical columns
            if df[col].notna().sum() > 0:
                value_counts = df[col].value_counts().head(10)  # Top 10 values
                if len(value_counts) > 1:
                    fig, ax = plt.subplots(figsize=(12, 6))
                    value_counts.plot(kind='bar', ax=ax)
                    ax.set_title(f'Top Values in {col}')
                    ax.set_xlabel(col)
                    ax.set_ylabel('Count')
                    plt.xticks(rotation=45, ha='right')

                    img = io.BytesIO()
                    plt.savefig(img, format='png', bbox_inches='tight', dpi=300)
                    img.seek(0)
                    plot_url = base64.b64encode(img.getvalue()).decode()
                    plots.append((f'Top Values: {col}', plot_url))
                    plt.close()

    except Exception as e:
        print(f"Error creating visualization: {e}")

    return plots

@app.route('/')
def index():
    """Main page - show master data if available"""
    df, metadata = load_master_data()

    if df is not None:
        # Process the attendance data
        processed_data = process_attendance_data(df)
        
        if processed_data:
            # Return the attendance tracker interface
            return render_template('index.html', 
                                 initial_data=json.dumps(processed_data),
                                 metadata=metadata)
        else:
            # Fallback to table view if processing fails
            plots = create_visualizations(df)
            return render_template('results.html',
                                 tables=[df.head(100).to_html(classes='data table table-striped',
                                                              table_id='dataTable')],
                                 titles=['Current Data'],
                                 plots=plots,
                                 metadata=metadata,
                                 show_upload_new=False)
    else:
        # No master data exists
        return render_template('no_data.html')

@app.route('/data/refresh')
def refresh_data():
    """API endpoint to refresh data from master file"""
    df, metadata = load_master_data()

    if df is not None:
        processed_data = process_attendance_data(df)
        return jsonify({
            'status': 'success',
            'data': processed_data,
            'metadata': metadata
        })
    else:
        return jsonify({'status': 'no_data'}), 404

@app.route('/health')
def health_check():
    df, metadata = load_master_data()
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
