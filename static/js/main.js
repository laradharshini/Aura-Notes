document.addEventListener('DOMContentLoaded', () => {
    const notesGrid = document.getElementById('notesGrid');
    const newNoteBtn = document.getElementById('newNoteBtn');
    const noteModal = document.getElementById('noteModal');
    const closeModal = document.getElementById('closeModal');
    const saveNoteBtn = document.getElementById('saveNote');
    const noteTitle = document.getElementById('noteTitle');
    const noteContent = document.getElementById('noteContent');
    const colorOpts = document.querySelectorAll('.color-opt');
    const logoutBtn = document.getElementById('logoutBtn');
    const searchInput = document.getElementById('searchInput');
    const noteTags = document.getElementById('noteTags');
    const lockNoteBtn = document.getElementById('lockNoteBtn');
    const lockStatus = document.getElementById('lockStatus');
    const unlockModal = document.getElementById('unlockModal');
    const passwordModal = document.getElementById('passwordModal');
    const unlockPasswordInput = document.getElementById('unlockPassword');
    const unlockError = document.getElementById('unlockError');
    const notePasswordInput = document.getElementById('notePasswordInput');
    const expirySelect = document.getElementById('expirySelect');
    const customExpiryContainer = document.getElementById('customExpiryContainer');
    const customExpiryDate = document.getElementById('customExpiryDate');

    let currentNoteId = null;
    let selectedColor = '#ffffff';
    let isCurrentlyLocked = false;
    let pendingUnlockId = null;

    const getTimeRemaining = (expiresAt) => {
        if (!expiresAt) return null;
        const now = new Date();
        const expiry = new Date(expiresAt);
        const diff = expiry - now;

        if (diff <= 1000) return 'Expired'; // 1 second grace

        const hours = Math.floor(diff / (1000 * 60 * 60));
        const days = Math.floor(hours / 24);

        if (days > 0) return `${days}d left`;
        if (hours > 0) return `${hours}h left`;
        const mins = Math.floor(diff / (1000 * 60));
        return `${mins}m left`;
    };

    const formatRelativeDate = (dateString) => {
        const date = new Date(dateString);
        const now = new Date();

        // Match by calendar date, not just time diff
        const localDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        const localNow = new Date(now.getFullYear(), now.getMonth(), now.getDate());

        const diffDays = Math.round((localNow - localDate) / (1000 * 60 * 60 * 24));

        if (diffDays === 0) return 'Today';
        if (diffDays === 1) return 'Yesterday';
        if (diffDays < 7) return `${diffDays} days ago`;

        return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric'
        });
    };

    const calculateNoteHealth = (note) => {
        let score = 0;

        // Title: +30%
        if (note.title && note.title.trim().length > 0) score += 30;

        // Tags: +20%
        if (note.tags && note.tags.length > 0) score += 20;

        // Length > 100 words: +30% (Approximate by 500 chars if not splitting)
        const wordCount = note.content ? note.content.trim().split(/\s+/).length : 0;
        if (wordCount > 100) score += 30;

        // Recent: +20% (Last 24h)
        const updatedAt = new Date(note.updated_at);
        const hoursSinceUpdate = (new Date() - updatedAt) / (1000 * 60 * 60);
        if (hoursSinceUpdate < 24) score += 20;

        return score;
    };

    // Fetch and display notes
    const fetchNotes = async (query = '') => {
        const url = query ? `/api/notes?q=${encodeURIComponent(query)}` : '/api/notes';
        const response = await fetch(url);
        if (response.status === 401) {
            window.location.href = '/login';
            return;
        }
        const notes = await response.json();
        renderNotes(notes);
    };

    const renderNotes = (notes) => {
        notesGrid.innerHTML = '';
        notes.forEach(note => {
            const card = document.createElement('div');
            card.className = `note-card ${note.is_locked ? 'locked' : ''}`;
            card.style.background = note.color || '#ffffff';
            card.onclick = () => {
                if (note.is_locked) {
                    openUnlockModal(note._id);
                } else {
                    openModal(note);
                }
            };

            const date = new Date(note.created_at).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric'
            });

            const timeRemaining = getTimeRemaining(note.expires_at);

            const health = calculateNoteHealth(note);
            const healthClass = health >= 80 ? 'high' : (health >= 40 ? 'mid' : 'low');

            card.innerHTML = `
                <div class="note-actions">
                    <button class="btn-icon-sm delete-btn" data-id="${note._id}">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
                <h3>
                    ${note.is_locked ? '<span class="title-lock-icon"><i class="fas fa-lock"></i></span>' : ''}
                    ${note.title || 'Untitled'}
                </h3>
                <div class="note-content">${note.content}</div>
                <div class="note-footer">
                    <div class="note-footer-top">
                        <div class="note-tags">
                            ${(note.tags || []).map(tag => `<span class="tag-badge">${tag}</span>`).join('')}
                            ${timeRemaining ? `
                                <div class="expiry-indicator">
                                    <i class="fas fa-clock"></i> ${timeRemaining}
                                </div>
                            ` : ''}
                        </div>
                        <div class="date">
                            ${formatRelativeDate(note.created_at)}
                        </div>
                    </div>
                    <div class="health-meta">
                        <span class="health-label">Health Score</span>
                        <span class="health-percent ${healthClass}">${health}%</span>
                    </div>
                </div>
            `;

            // Delete functionality
            card.querySelector('.delete-btn').onclick = (e) => {
                e.stopPropagation();
                deleteNote(note._id);
            };

            notesGrid.appendChild(card);
        });
    };

    const openModal = (note = null) => {
        if (note) {
            currentNoteId = note._id;
            noteTitle.value = note.title;
            noteContent.innerHTML = note.content;
            noteTags.value = (note.tags || []).join(', ');
            selectedColor = note.color;

            if (note.expires_at) {
                expirySelect.value = 'custom';
                customExpiryContainer.style.display = 'block';
                const date = new Date(note.expires_at);

                // Adjust for local timezone to show correct local time in datetime-local input
                const offset = date.getTimezoneOffset() * 60000;
                const localISOTime = (new Date(date - offset)).toISOString().slice(0, 16);
                customExpiryDate.value = localISOTime;
            } else {
                expirySelect.value = 'never';
                customExpiryContainer.style.display = 'none';
            }
            updateClearExpiryVisibility();

            isCurrentlyLocked = note.is_locked || false;
        } else {
            currentNoteId = null;
            noteTitle.value = '';
            noteContent.innerHTML = '';
            noteTags.value = '';
            selectedColor = '#ffffff';
            isCurrentlyLocked = false;
            expirySelect.value = 'never';
            customExpiryContainer.style.display = 'none';
            updateClearExpiryVisibility();
        }

        updateColorSelection(selectedColor);
        noteModal.classList.add('active');
    };

    const setDefaultExpiryDate = () => {
        // Default to 1 hour from now
        const now = new Date();
        now.setHours(now.getHours() + 1);
        now.setSeconds(0);
        now.setMilliseconds(0);

        const offset = now.getTimezoneOffset() * 60000;
        const localISOTime = (new Date(now - offset)).toISOString().slice(0, 16);
        customExpiryDate.value = localISOTime;
    };

    const clearExpiryBtn = document.getElementById('clearExpiryBtn');

    const updateClearExpiryVisibility = () => {
        if (expirySelect.value !== 'never') {
            clearExpiryBtn.style.display = 'flex';
        } else {
            clearExpiryBtn.style.display = 'none';
        }
    };

    expirySelect.addEventListener('change', () => {
        if (expirySelect.value === 'custom') {
            customExpiryContainer.style.display = 'block';
            if (!customExpiryDate.value) {
                setDefaultExpiryDate();
            }
        } else {
            customExpiryContainer.style.display = 'none';
        }
        updateClearExpiryVisibility();
    });

    clearExpiryBtn.addEventListener('click', () => {
        expirySelect.value = 'never';
        customExpiryContainer.style.display = 'none';
        updateClearExpiryVisibility();
        // Force update of health indicator if it's currently saving
    });

    const updateLockUI = () => {
        if (isCurrentlyLocked) {
            lockNoteBtn.innerHTML = '<i class="fas fa-lock"></i>';
            lockNoteBtn.title = "Unlock Note (Dashboard)";
            lockStatus.style.display = 'flex';
        } else {
            lockNoteBtn.innerHTML = '<i class="fas fa-unlock"></i>';
            lockNoteBtn.title = "Lock Note";
            lockStatus.style.display = 'none';
        }
    };

    const openUnlockModal = (id) => {
        pendingUnlockId = id;
        unlockPasswordInput.value = '';
        unlockError.style.display = 'none';
        unlockModal.classList.add('active');
    };

    const updateColorSelection = (color) => {
        colorOpts.forEach(opt => {
            if (opt.dataset.color === color) {
                opt.classList.add('active');
            } else {
                opt.classList.remove('active');
            }
        });
    };

    const saveNote = async (password = null) => {
        const noteData = {
            title: noteTitle.value,
            content: noteContent.innerHTML,
            tags: noteTags.value.split(',').map(tag => tag.trim()).filter(tag => tag !== ''),
            color: selectedColor
        };

        const expiryVal = expirySelect.value;
        if (expiryVal === '1') {
            const date = new Date();
            date.setDate(date.getDate() + 1);
            noteData.expires_at = date.toISOString();
        } else if (expiryVal === '7') {
            const date = new Date();
            date.setDate(date.getDate() + 7);
            noteData.expires_at = date.toISOString();
        } else if (expiryVal === 'custom' && customExpiryDate.value) {
            const expiryDate = new Date(customExpiryDate.value);
            if (expiryDate <= new Date()) {
                alert('The expiry time you selected is in the past. Please pick a future time (use 24-hour format, e.g., 21:00 for 9 PM).');
                return;
            }
            noteData.expires_at = expiryDate.toISOString();
        } else {
            noteData.expires_at = null;
        }

        if (password !== null) {
            noteData.password = password;
            noteData.is_locked = !!password;
        }

        if (currentNoteId) {
            await fetch(`/api/notes/${currentNoteId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(noteData)
            });
        } else {
            await fetch('/api/notes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(noteData)
            });
        }

        noteModal.classList.remove('active');
        fetchNotes();
    };

    const deleteNote = async (id) => {
        if (confirm('Are you sure you want to delete this note?')) {
            const response = await fetch(`/api/notes/${id}`, { method: 'DELETE' });
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            fetchNotes();
        }
    };

    const logout = async () => {
        const response = await fetch('/api/auth/logout', { method: 'POST' });
        if (response.ok) {
            window.location.href = '/login';
        }
    };

    // Event Listeners
    newNoteBtn.onclick = () => openModal();
    closeModal.onclick = () => noteModal.classList.remove('active');
    saveNoteBtn.onclick = () => saveNote();
    logoutBtn.onclick = logout;

    lockNoteBtn.onclick = () => {
        if (isCurrentlyLocked) {
            if (confirm('Are you sure you want to remove password protection from this note?')) {
                saveNote(''); // Empty string removes password
            }
        } else {
            notePasswordInput.value = '';
            passwordModal.classList.add('active');
        }
    };

    document.getElementById('confirmPassword').onclick = () => {
        const pass = notePasswordInput.value;
        if (pass) {
            saveNote(pass);
            passwordModal.classList.remove('active');
        } else {
            alert('Please enter a password');
        }
    };

    document.getElementById('cancelPassword').onclick = () => {
        passwordModal.classList.remove('active');
    };

    document.getElementById('confirmUnlock').onclick = async () => {
        const password = unlockPasswordInput.value;
        const response = await fetch(`/api/notes/${pendingUnlockId}/unlock`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });

        if (response.ok) {
            const note = await response.json();
            unlockModal.classList.remove('active');
            openModal(note);
        } else {
            unlockError.textContent = 'Invalid password';
            unlockError.style.display = 'block';
        }
    };

    document.getElementById('cancelUnlock').onclick = () => {
        unlockModal.classList.remove('active');
    };

    expirySelect.onchange = () => {
        if (expirySelect.value === 'custom') {
            customExpiryContainer.style.display = 'block';
            if (!customExpiryDate.value) {
                setDefaultExpiryDate();
            }
        } else {
            customExpiryContainer.style.display = 'none';
        }
    };

    // Search input handler
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            fetchNotes(e.target.value);
        }, 300); // 300ms debounce
    });

    colorOpts.forEach(opt => {
        opt.onclick = () => {
            selectedColor = opt.dataset.color;
            updateColorSelection(selectedColor);
        };
    });

    // Toolbar Logic
    document.querySelectorAll('.toolbar-btn').forEach(btn => {
        btn.onclick = (e) => {
            e.preventDefault();
            const command = btn.dataset.command;
            document.execCommand(command, false, null);
            noteContent.focus();
        };
    });

    // Close modal on outside click
    window.onclick = (e) => {
        if (e.target === noteModal) {
            noteModal.classList.remove('active');
        }
    };

    // Initial fetch
    fetchNotes();
});
