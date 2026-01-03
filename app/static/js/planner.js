
document.addEventListener('DOMContentLoaded', function() {
    // 1. Mirror global prefs
    document.querySelectorAll('.architect-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const time = document.querySelector('input[name="global_max_time"]').value;
            const cal = document.querySelector('input[name="global_max_cal"]').value;
            const form = this.closest('form');
            form.querySelector('.pref-time-mirror').value = time;
            form.querySelector('.pref-cal-mirror').value = cal;
        });
    });

    // 2. Fetch and render the Shopping List
    const previewBtn = document.getElementById('previewBtn');
    if (previewBtn) {
        previewBtn.addEventListener('click', function() {
            const mainList = document.getElementById('mainList');
            const basicsList = document.getElementById('basicsList');
            const loading = document.getElementById('modalLoading');
            const content = document.getElementById('modalContent');

            loading.style.display = 'block';
            content.style.display = 'none';

            fetch('/api/shopping_list_preview')
                .then(response => response.json())
                .then(data => {
                    mainList.innerHTML = '';
                    const grouped = data.grouped_shopping_list;
                    for (const category in grouped) {
                        const items = grouped[category];
                        if (items.length > 0) {
                            const header = document.createElement('li');
                            header.className = 'list-group-item bg-light fw-bold text-uppercase small py-1 mt-2';
                            header.style.color = '#2e7d32'; 
                            header.innerText = category;
                            mainList.appendChild(header);

                            items.forEach(item => {
                                const li = document.createElement('li');
                                li.className = 'list-group-item d-flex justify-content-between align-items-center border-0 ps-3 py-1';
                                const escapedName = item.name.replace(/'/g, "\\'");
                                li.innerHTML = `
                                    <span class="small">
                                        ${item.name} 
                                        <i class="bi bi-pencil-square text-primary ms-1" 
                                           style="cursor: pointer; opacity: 0.6;" 
                                           onclick="openReclassifyPicker('${escapedName}')"></i>
                                    </span>
                                    <span class="badge bg-white text-dark border fw-normal">${item.quantity} ${item.unit}</span>
                                `;
                                mainList.appendChild(li);
                            });
                        }
                    }
                    basicsList.innerText = data.basics_check_list.length > 0 ? data.basics_check_list.join(', ') : 'Nothing extra needed.';
                    loading.style.display = 'none';
                    content.style.display = 'block';
                })
                .catch(error => {
                    console.error('Error:', error);
                    loading.innerHTML = '<p class="text-danger">⚠️ Error loading list.</p>';
                });
        });
    }

    // 3. Reclassification Logic
    window.openReclassifyPicker = function(name) {
        document.getElementById('targetIngName').value = name;
        document.getElementById('reclassifyTitle').innerText = `Move: ${name}`;
        const modalEl = document.getElementById('reclassifyModal');
        const myModal = new bootstrap.Modal(modalEl);
        myModal.show();
    };

    window.confirmReclassify = function(newCat) {
        const name = document.getElementById('targetIngName').value;
        const reclassifyModalEl = document.getElementById('reclassifyModal');
        const modalInstance = bootstrap.Modal.getInstance(reclassifyModalEl);

        fetch('/api/update_ingredient_category', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name, category: newCat})
        })
        .then(res => res.json())
        .then(data => {
            if(data.status === 'success') {
                modalInstance.hide();
                const toast = new bootstrap.Toast(document.getElementById('successToast'));
                toast.show();
                document.getElementById('previewBtn').click();
            }
        });
    };

    // 4. Finalise Plan
    const finaliseBtn = document.getElementById('finaliseBtn');
    const executeFinaliseBtn = document.getElementById('executeFinaliseBtn');
    const finaliseModalEl = document.getElementById('finaliseConfirmModal');
    const finaliseModal = new bootstrap.Modal(finaliseModalEl);

    if (finaliseBtn) {
        finaliseBtn.addEventListener('click', function() {
            finaliseModal.show();
        });
    }

    if (executeFinaliseBtn) {
        executeFinaliseBtn.addEventListener('click', function() {
            executeFinaliseBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Finalising...';
            executeFinaliseBtn.disabled = true;

            fetch('/api/finalise_plan', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        finaliseModal.hide();
                        window.location.href = '/current-plan';
                    } else {
                        alert("Error: " + data.message);
                        executeFinaliseBtn.disabled = false;
                        executeFinaliseBtn.innerText = 'Confirm Weekly Plan';
                    }
                });
        });
    }
});
