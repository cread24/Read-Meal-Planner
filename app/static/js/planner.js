
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

    // 5. Recipe Search and Favourites Selection

    // A. Event Listener for the Search/Fav buttons
    document.querySelectorAll('.search-trigger').forEach(btn => {
        btn.addEventListener('click', function() {
            // Convert attributes to the types we need
            const slot = parseInt(this.getAttribute('data-slot'));
            const favOnly = this.getAttribute('data-fav') === 'true';
            
            // Call the modal opener
            openSearchModal(slot, favOnly);
        });
    });

    // B. The Modal Logic
    let currentTargetSlot = 0;
    let isFavOnly = false;

    window.openSearchModal = function(slotIndex, favOnly) {
        currentTargetSlot = slotIndex;
        isFavOnly = favOnly;
        
        const modalTitle = document.getElementById('modalTitle');
        const queryInput = document.getElementById('recipeQuery');
        const resultsContainer = document.getElementById('searchResults');
        
        // Update UI based on mode
        modalTitle.innerText = favOnly ? "⭐ Your Favourites" : "🔍 Search Recipes";
        queryInput.value = "";
        queryInput.placeholder = favOnly ? "Search within favourites..." : "Type a recipe name...";
        resultsContainer.innerHTML = '<p class="text-center text-muted py-4 small">Start typing to find a meal...</p>';
        
        const modalEl = document.getElementById('recipeSearchModal');
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
        
        // Auto-load favourites if in fav mode
        if (favOnly) {
            performSearch("");
        }
    };

    // C. The Search Function
    function performSearch(query) {
        const container = document.getElementById('searchResults');
        
        fetch(`/api/search_recipes?q=${encodeURIComponent(query)}&favourites=${isFavOnly}`)
            .then(res => res.json())
            .then(data => {
                if (data.length === 0) {
                    container.innerHTML = '<p class="text-center text-muted py-4 small">No matching recipes found.</p>';
                    return;
                }
                
                container.innerHTML = data.map(r => `
                    <form action="/select_recipe/${currentTargetSlot}/${r.id}" method="POST">
                        <button type="submit" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center py-3">
                            <div>
                                <div class="fw-bold text-dark">${r.name}</div>
                                <small class="text-muted text-uppercase" style="font-size: 0.7rem;">
                                    ${r.category} • ${r.time} MINS
                                </small>
                            </div>
                            <i class="bi bi-plus-circle text-success fs-5"></i>
                        </button>
                    </form>
                `).join('');
            })
            .catch(err => {
                console.error("Search error:", err);
                container.innerHTML = '<p class="text-danger text-center py-4 small">Error connecting to server.</p>';
            });
    }

    // D. Attach listener to the input field
    const searchInput = document.getElementById('recipeQuery');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => performSearch(e.target.value));
    }

    // Save scroll position before the page unloads
    window.addEventListener('beforeunload', () => {
        localStorage.setItem('scrollPosition', window.scrollY);
    });

    // Restore scroll position when the page loads
    window.addEventListener('load', () => {
        const scrollPos = localStorage.getItem('scrollPosition');
        if (scrollPos) {
            window.scrollTo(0, parseInt(scrollPos));
            localStorage.removeItem('scrollPosition');
        }
    });

    window.openRecipeReclassify = function(recipeId, recipeName) {
    const form = document.getElementById('reclassifyRecipeForm');
    const title = document.getElementById('recTitle');
    
    // Set the action URL to the specific recipe ID
    form.action = `/reclassify_recipe/${recipeId}`;
    title.innerText = `Move ${recipeName} to:`;
    
    const modal = new bootstrap.Modal(document.getElementById('recipeReclassifyModal'));
    modal.show();
};
});
