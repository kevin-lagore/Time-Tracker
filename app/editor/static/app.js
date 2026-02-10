/* Work Log Editor — minimal JS */

let isDirty = false;

function markDirty() {
    isDirty = true;
}

function clearDirty() {
    isDirty = false;
}

// Unsaved changes warning
window.addEventListener('beforeunload', function (e) {
    if (isDirty) {
        e.preventDefault();
        e.returnValue = '';
    }
});

// Select all checkboxes
function toggleSelectAll(masterCheckbox) {
    const checkboxes = document.querySelectorAll('.entry-checkbox');
    checkboxes.forEach(cb => { cb.checked = masterCheckbox.checked; });
    updateBulkIds();
}

// Update hidden field with selected entry IDs
function updateBulkIds() {
    const checkboxes = document.querySelectorAll('.entry-checkbox:checked');
    const ids = Array.from(checkboxes).map(cb => cb.value);
    const el = document.getElementById('bulk-entry-ids');
    if (el) el.value = ids.join(',');
}

// Confirm bulk operation
function confirmBulk() {
    const ids = document.getElementById('bulk-entry-ids');
    if (!ids || !ids.value) {
        alert('No entries selected.');
        return false;
    }
    const count = ids.value.split(',').length;
    return confirm(`Apply changes to ${count} selected entries?`);
}

// Bulk project selection handler
function bulkProjectChanged(sel) {
    const opt = sel.options[sel.selectedIndex];
    const idEl = document.getElementById('bulk-project-id');
    const clientEl = document.getElementById('bulk-client-name');
    const wsEl = document.getElementById('bulk-workspace-id');

    if (idEl) idEl.value = opt.dataset?.projectId || '';
    if (clientEl) clientEl.value = opt.dataset?.clientName || '';
    if (wsEl) wsEl.value = opt.dataset?.workspaceId || '';
}

// Auto-dismiss alerts after 4 seconds
document.addEventListener('DOMContentLoaded', function () {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.3s';
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300);
        }, 4000);
    });
});
