let workbookData = {};
let currentData = null;

document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('fileInput');
    const uploadBtn = document.getElementById('uploadBtn');
    const monthSelect = document.getElementById('monthSelect');

    uploadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileUpload);
    monthSelect.addEventListener('change', handleMonthChange);
});

function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    showLoading(true);
    showFileStatus('Uploading and processing file...', 'info');

    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            workbookData = data.data;
            populateMonthSelector();
            showFileStatus(data.message, 'success');
            document.getElementById('controls').style.display = 'flex';
        } else {
            showFileStatus(data.error || 'Error processing file', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showFileStatus('Error uploading file. Please try again.', 'error');
    })
    .finally(() => {
        showLoading(false);
    });
}

function populateMonthSelector() {
    const monthSelect = document.getElementById('monthSelect');
    monthSelect.innerHTML = '<option value="">Choose a month...</option>';

    Object.keys(workbookData).forEach(sheetName => {
        const option = document.createElement('option');
        option.value = sheetName;
        option.textContent = sheetName;
        monthSelect.appendChild(option);
    });

    // Auto-select first month
    if (Object.keys(workbookData).length > 0) {
        const firstMonth = Object.keys(workbookData)[0];
        monthSelect.value = firstMonth;
        handleMonthChange();
    }
}

function handleMonthChange() {
    const selectedMonth = document.getElementById('monthSelect').value;
    
    if (!selectedMonth || !workbookData[selectedMonth]) {
        showNoData();
        return;
    }

    currentData = workbookData[selectedMonth];
    displayData();
    updateStats();
    displaySummary();
}

function displayData() {
    if (!currentData || !currentData.employees.length) {
        showNoData();
        return;
    }

    document.getElementById('noData').style.display = 'none';
    document.getElementById('dataSection').style.display = 'block';

    const table = document.getElementById('employeeTable');
    const header = document.getElementById('tableHeader');
    const tbody = document.getElementById('tableBody');

    // Clear existing content
    header.innerHTML = '';
    tbody.innerHTML = '';

    // Create header row
    const headerRow = document.createElement('tr');
    
    // Fixed columns
    ['Employee', 'ID', 'Department', 'Manager', 'Shift'].forEach(text => {
        const th = document.createElement('th');
        th.textContent = text;
        headerRow.appendChild(th);
    });

    // Date columns
    currentData.dates.forEach(dateInfo => {
        const th = document.createElement('th');
        const date = new Date(dateInfo.date);
        const day = date.getDate();
        th.innerHTML = `${day}<br><small>${dateInfo.day.substring(0, 3)}</small>`;
        th.style.minWidth = '60px';
        headerRow.appendChild(th);
    });

    // Summary columns
    ['WFO', 'WFH', 'SL', 'PL'].forEach(type => {
        const th = document.createElement('th');
        th.textContent = type;
        th.style.backgroundColor = '#34495e';
        headerRow.appendChild(th);
    });

    header.appendChild(headerRow);

    // Create data rows
    currentData.employees.forEach(employee => {
        const row = document.createElement('tr');

        // Fixed columns
        [
            employee.name,
            employee.person_id,
            employee.department,
            employee.team_manager,
            employee.shift_timings
        ].forEach((text, index) => {
            const td = document.createElement('td');
            td.textContent = text || '';
            if (index === 0) td.className = 'employee-info';
            row.appendChild(td);
        });

        // Attendance columns
        currentData.dates.forEach((dateInfo, dateIdx) => {
            const td = document.createElement('td');
            td.className = 'day-cell';
            
            const status = employee.attendance[dateIdx];
            if (status) {
                td.textContent = status;
                td.classList.add(status.toLowerCase());
            } else if (dateInfo.day === 'Saturday' || dateInfo.day === 'Sunday') {
                td.textContent = '-';
                td.classList.add('weekend');
            } else {
                td.textContent = '-';
            }
            
            row.appendChild(td);
        });

        // Summary columns
        ['WFO', 'WFH', 'SL', 'PL'].forEach(type => {
            const td = document.createElement('td');
            td.textContent = employee.summary[type] || 0;
            td.style.fontWeight = 'bold';
            td.style.textAlign = 'center';
            row.appendChild(td);
        });

        tbody.appendChild(row);
    });
}

function updateStats() {
    if (!currentData) return;

    document.getElementById('totalEmployees').textContent = currentData.total_employees;
    document.getElementById('workingDays').textContent = currentData.working_days;
}

function displaySummary() {
    if (!currentData || !currentData.employees.length) return;

    const summaryCards = document.getElementById('summaryCards');
    summaryCards.innerHTML = '';

    // Calculate totals
    const totals = { WFO: 0, WFH: 0, SL: 0, PL: 0 };
    currentData.employees.forEach(emp => {
        Object.keys(totals).forEach(key => {
            totals[key] += emp.summary[key] || 0;
        });
    });

    // Create summary cards
    Object.entries(totals).forEach(([type, count]) => {
        const card = document.createElement('div');
        card.className = 'summary-card';
        
        const title = document.createElement('h3');
        title.textContent = `${type} Summary`;
        card.appendChild(title);

        const totalItem = document.createElement('div');
        totalItem.className = 'summary-item';
        totalItem.innerHTML = `<span>Total ${type} Days:</span><strong>${count}</strong>`;
        card.appendChild(totalItem);

        const avgItem = document.createElement('div');
        avgItem.className = 'summary-item';
        const avg = currentData.total_employees > 0 ? (count / currentData.total_employees).toFixed(1) : 0;
        avgItem.innerHTML = `<span>Average per Employee:</span><strong>${avg}</strong>`;
        card.appendChild(avgItem);

        summaryCards.appendChild(card);
    });
}

function showLoading(show) {
    document.getElementById('loadingSpinner').style.display = show ? 'block' : 'none';
}

function showFileStatus(message, type) {
    const status = document.getElementById('fileStatus');
    status.textContent = message;
    status.className = `file-status ${type}`;
    status.style.display = 'block';
    
    if (type === 'success') {
        setTimeout(() => {
            status.style.display = 'none';
        }, 3000);
    }
}

function showNoData() {
    document.getElementById('dataSection').style.display = 'none';
    document.getElementById('noData').style.display = 'block';
}
