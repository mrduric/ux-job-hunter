// ── State ──────────────────────────────────────────────────────────────────────
const state = {
    currentStep: 1,
    resumeText: '',
    apiKey: '',
    jobTitles: [],
    skills: [],
    locations: [],
    experienceLevels: [],
    postedWithinDays: 7,
    excludeCompanies: '',
    results: [],
    sessionId: '',
};

let sortColumn = 'fit_score';
let sortDirection = 'desc';

// ── Navigation ────────────────────────────────────────────────────────────────

function showStep(n) {
    document.querySelectorAll('.step-content').forEach(el => el.classList.add('hidden'));
    const target = document.getElementById(`step-${n}`);
    if (target) target.classList.remove('hidden');
    state.currentStep = n;
    updateStepIndicator(n);
}

function goToStep(n) {
    if (n === 3) populateSummary();
    showStep(n);
}

function updateStepIndicator(current) {
    for (let i = 1; i <= 4; i++) {
        const indicator = document.querySelector(`[data-step-indicator="${i}"]`);
        const circle = indicator.querySelector('.step-circle');
        const label = indicator.querySelector('.step-label');
        const line = document.querySelector(`[data-step-line="${i}"]`);

        if (i < current) {
            // Completed
            circle.className = 'step-circle flex items-center justify-center w-8 h-8 rounded-full bg-indigo-600 text-white text-sm font-semibold';
            circle.innerHTML = '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>';
            label.className = 'step-label ml-2 text-sm font-medium text-indigo-600 hidden sm:inline';
            if (line) line.className = 'flex-1 h-0.5 mx-3 bg-indigo-600';
        } else if (i === current) {
            // Current
            circle.className = 'step-circle flex items-center justify-center w-8 h-8 rounded-full bg-indigo-600 text-white text-sm font-semibold';
            circle.textContent = i;
            label.className = 'step-label ml-2 text-sm font-medium text-indigo-600 hidden sm:inline';
            if (line) line.className = 'flex-1 h-0.5 mx-3 bg-gray-200';
        } else {
            // Upcoming
            circle.className = 'step-circle flex items-center justify-center w-8 h-8 rounded-full bg-gray-200 text-gray-500 text-sm font-semibold';
            circle.textContent = i;
            label.className = 'step-label ml-2 text-sm font-medium text-gray-500 hidden sm:inline';
            if (line) line.className = 'flex-1 h-0.5 mx-3 bg-gray-200';
        }
    }
}

// ── Error Handling ─────────────────────────────────────────────────────────────

function showError(message) {
    const alert = document.getElementById('error-alert');
    const msg = document.getElementById('error-message');
    msg.textContent = message;
    alert.classList.remove('hidden');
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function hideError() {
    document.getElementById('error-alert').classList.add('hidden');
}

// ── Step 1: Upload Resume ─────────────────────────────────────────────────────

function onFileSelected() {
    const fileInput = document.getElementById('resume-file');
    const fileName = document.getElementById('file-name');
    const uploadBtn = document.getElementById('upload-btn');
    if (fileInput.files.length > 0) {
        fileName.textContent = fileInput.files[0].name;
        fileName.classList.remove('hidden');
        uploadBtn.disabled = false;
    }
}

async function uploadResume() {
    const fileInput = document.getElementById('resume-file');
    if (!fileInput.files.length) {
        showError('Please select a file first.');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    const btn = document.getElementById('upload-btn');
    const spinner = document.getElementById('upload-spinner');
    setLoading(btn, spinner, true);
    hideError();

    try {
        const res = await fetch('/api/upload-resume', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || `Upload failed (${res.status})`);
        }

        const data = await res.json();
        state.resumeText = data.resume_text || data.text || '';
        state.sessionId = data.session_id || '';

        const textarea = document.getElementById('resume-text');
        textarea.value = state.resumeText;
        document.getElementById('resume-text-section').classList.remove('hidden');
    } catch (err) {
        showError(err.message);
    } finally {
        setLoading(btn, spinner, false);
    }
}

// ── Step 2: Analyze Resume ────────────────────────────────────────────────────

function toggleApiKeyVisibility() {
    const input = document.getElementById('api-key');
    const toggle = document.getElementById('api-key-toggle');
    if (input.type === 'password') {
        input.type = 'text';
        toggle.textContent = 'Hide';
    } else {
        input.type = 'password';
        toggle.textContent = 'Show';
    }
}

async function analyzeResume() {
    // Sync resume text from textarea in case user edited it
    const textarea = document.getElementById('resume-text');
    if (textarea) state.resumeText = textarea.value;

    state.apiKey = document.getElementById('api-key').value.trim();

    if (!state.apiKey) {
        showError('Please enter your API key.');
        return;
    }
    if (!state.resumeText) {
        showError('No resume text available. Please upload a resume first.');
        return;
    }

    const btn = document.getElementById('analyze-btn');
    const spinner = document.getElementById('analyze-spinner');
    setLoading(btn, spinner, true);
    hideError();

    try {
        const res = await fetch('/api/analyze-resume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                resume_text: state.resumeText,
                api_key: state.apiKey,
            }),
        });

        if (res.status === 401) {
            throw new Error('Invalid API key. Please check your key and try again.');
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || `Analysis failed (${res.status})`);
        }

        const data = await res.json();

        state.jobTitles = data.suggested_titles || data.job_titles || [];
        state.skills = data.key_skills || data.skills || [];
        state.locations = data.locations || [];
        // experience_level can be a string or array
        const expLevel = data.experience_level || data.experience_levels || [];
        state.experienceLevels = Array.isArray(expLevel) ? expLevel : [expLevel];

        renderChips('job-titles', state.jobTitles);
        renderChips('skills', state.skills);
        renderChips('locations', state.locations);
        syncExperienceCheckboxes();

        document.getElementById('analysis-results').classList.remove('hidden');
    } catch (err) {
        showError(err.message);
    } finally {
        setLoading(btn, spinner, false);
    }
}

function updateExperienceLevels() {
    state.experienceLevels = [];
    document.querySelectorAll('.exp-level-checkbox:checked').forEach(cb => {
        state.experienceLevels.push(cb.value);
    });
}

function syncExperienceCheckboxes() {
    document.querySelectorAll('.exp-level-checkbox').forEach(cb => {
        cb.checked = state.experienceLevels.includes(cb.value);
    });
}

// ── Chip Management ───────────────────────────────────────────────────────────

function getChipStateKey(containerId) {
    const map = {
        'job-titles': 'jobTitles',
        'skills': 'skills',
        'locations': 'locations',
    };
    return map[containerId];
}

function renderChips(containerId, values) {
    const container = document.getElementById(`${containerId}-chips`);
    container.innerHTML = '';
    values.forEach(v => createChipElement(container, containerId, v));
}

function createChipElement(container, containerId, value) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.setAttribute('data-value', value);

    const text = document.createElement('span');
    text.textContent = value;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.innerHTML = '&times;';
    btn.onclick = () => removeChip(containerId, value);

    chip.appendChild(text);
    chip.appendChild(btn);
    container.appendChild(chip);
}

function addChip(containerId, value) {
    const key = getChipStateKey(containerId);
    if (!key) return;
    value = value.trim();
    if (!value || state[key].includes(value)) return;
    state[key].push(value);

    const container = document.getElementById(`${containerId}-chips`);
    createChipElement(container, containerId, value);
}

function removeChip(containerId, value) {
    const key = getChipStateKey(containerId);
    if (!key) return;
    state[key] = state[key].filter(v => v !== value);
    renderChips(containerId, state[key]);
}

function addChipFromInput(containerId) {
    const input = document.getElementById(`${containerId}-input`);
    if (!input) return;
    const value = input.value.trim();
    if (value) {
        addChip(containerId, value);
        input.value = '';
    }
    input.focus();
}

// ── Step 3: Summary ───────────────────────────────────────────────────────────

function populateSummary() {
    document.getElementById('summary-titles').textContent =
        state.jobTitles.length ? state.jobTitles.join(', ') : 'None selected';
    document.getElementById('summary-locations').textContent =
        state.locations.length ? state.locations.join(', ') : 'None selected';
    document.getElementById('summary-experience').textContent =
        state.experienceLevels.length ? state.experienceLevels.join(', ') : 'None selected';
}

// ── Step 4: Search ────────────────────────────────────────────────────────────

async function startSearch() {
    state.postedWithinDays = parseInt(document.getElementById('posted-within').value, 10);
    state.excludeCompanies = document.getElementById('exclude-companies').value.trim();

    const btn = document.getElementById('search-btn');
    const spinner = document.getElementById('search-spinner');
    setLoading(btn, spinner, true);
    hideError();

    goToStep(4);

    // Reset progress UI
    document.getElementById('search-progress').classList.remove('hidden');
    document.getElementById('results-container').classList.add('hidden');
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('search-phase').textContent = 'Discovering jobs...';
    document.getElementById('search-status').textContent = 'Initializing...';
    document.getElementById('discovery-stats').classList.remove('hidden');
    document.getElementById('discovery-count').textContent = '0';
    document.getElementById('source-badges').innerHTML = '';

    try {
        const res = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                resume_text: state.resumeText,
                api_key: state.apiKey,
                job_titles: state.jobTitles,
                locations: state.locations,
                experience_levels: state.experienceLevels,
                posted_within_days: state.postedWithinDays,
                exclude_companies: state.excludeCompanies ? state.excludeCompanies.split(',').map(s => s.trim()).filter(Boolean) : [],
            }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || `Search failed (${res.status})`);
        }

        // Read SSE stream
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line in buffer
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        handleSearchEvent(event);
                    } catch (_) {
                        // Ignore malformed JSON lines
                    }
                }
            }
        }

        // Process any remaining buffer
        if (buffer.startsWith('data: ')) {
            try {
                const event = JSON.parse(buffer.slice(6));
                handleSearchEvent(event);
            } catch (_) {}
        }
    } catch (err) {
        showError(err.message);
    } finally {
        setLoading(btn, spinner, false);
    }
}

function handleSearchEvent(event) {
    const phase = document.getElementById('search-phase');
    const bar = document.getElementById('progress-bar');
    const status = document.getElementById('search-status');

    const discoveryStats = document.getElementById('discovery-stats');
    const discoveryCount = document.getElementById('discovery-count');
    const sourceBadges = document.getElementById('source-badges');

    switch (event.type) {
        case 'status':
            if (event.phase === 'discovery') {
                phase.textContent = 'Discovering jobs...';
                discoveryStats.classList.remove('hidden');
                bar.style.width = '0%';
            }
            else if (event.phase === 'evaluation') {
                phase.textContent = 'Evaluating fit with AI...';
                discoveryStats.classList.add('hidden');
            }
            else if (event.phase === 'discovery_complete') phase.textContent = 'Discovery complete';
            if (event.message) status.textContent = event.message;
            break;

        case 'progress':
            if (event.phase === 'discovery') {
                phase.textContent = 'Discovering jobs...';
                discoveryStats.classList.remove('hidden');
                const found = event.found_so_far || 0;
                discoveryCount.textContent = found;
                status.textContent = `Scanning ${event.source || ''}: ${event.company || ''}...`;
                // Update source badge
                updateSourceBadge(sourceBadges, event.source, event.company);
            } else if (event.phase === 'evaluation') {
                discoveryStats.classList.add('hidden');
                phase.textContent = 'Evaluating fit with AI...';
                const pct = event.total ? Math.round((event.current / event.total) * 100) : 0;
                bar.style.width = `${pct}%`;
                status.textContent = `Evaluating [${event.current}/${event.total}]: ${event.title || ''} @ ${event.company || ''}`;
            }
            break;

        case 'complete':
            bar.style.width = '100%';
            bar.classList.remove('progress-animated');
            phase.textContent = 'Search complete';
            status.textContent = `Found ${(event.jobs || []).length} matching jobs.`;
            state.results = event.jobs || [];
            state.sessionId = event.session_id || state.sessionId;
            setTimeout(() => {
                document.getElementById('search-progress').classList.add('hidden');
                renderResults(state.results);
            }, 600);
            break;

        case 'error':
            showError(event.message || 'An error occurred during search.');
            break;

        default:
            if (event.message) status.textContent = event.message;
            break;
    }
}

// ── Discovery Source Badges ───────────────────────────────────────────────

const sourceColors = {
    greenhouse: 'bg-green-100 text-green-700',
    lever: 'bg-blue-100 text-blue-700',
    ashby: 'bg-purple-100 text-purple-700',
    smartrecruiters: 'bg-orange-100 text-orange-700',
    workable: 'bg-teal-100 text-teal-700',
    bamboohr: 'bg-pink-100 text-pink-700',
    amazon_jobs: 'bg-yellow-100 text-yellow-700',
    workday: 'bg-cyan-100 text-cyan-700',
};

const sourceLabels = {
    greenhouse: 'Greenhouse',
    lever: 'Lever',
    ashby: 'Ashby',
    smartrecruiters: 'SmartRecruiters',
    workable: 'Workable',
    bamboohr: 'BambooHR',
    amazon_jobs: 'Amazon',
    workday: 'Workday',
};

function updateSourceBadge(container, source, company) {
    if (!source) return;
    let badge = container.querySelector(`[data-source="${source}"]`);
    if (!badge) {
        badge = document.createElement('span');
        badge.setAttribute('data-source', source);
        const color = sourceColors[source] || 'bg-gray-100 text-gray-700';
        badge.className = `inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${color}`;
        container.appendChild(badge);
    }
    const label = sourceLabels[source] || source;
    // Show a spinner dot while actively scanning this source
    badge.innerHTML = `<span class="inline-block w-1.5 h-1.5 rounded-full bg-current opacity-60 animate-pulse"></span> ${esc(label)}`;
}

// ── Results Rendering ─────────────────────────────────────────────────────────

function renderResults(jobs) {
    const container = document.getElementById('results-container');
    const body = document.getElementById('results-body');
    const cards = document.getElementById('results-cards');
    const countEl = document.getElementById('results-count');

    countEl.textContent = `${jobs.length} job${jobs.length !== 1 ? 's' : ''} found`;
    body.innerHTML = '';
    cards.innerHTML = '';

    jobs.forEach((job, idx) => {
        // Normalize field names (backend sends fit_score/seniority_level/fit_reasoning/cover_letter_hook)
        const score = job.fit_score ?? job.score ?? 0;
        const level = job.seniority_level || job.level || '';
        const reasoning = job.fit_reasoning || job.reasoning || '';
        const hook = job.cover_letter_hook || job.hook || '';
        const gaps = job.skill_gaps || '';
        const matchingSkills = job.matching_skills || '';

        const scoreBg = score >= 7 ? 'bg-green-100 text-green-800'
            : score >= 5 ? 'bg-yellow-100 text-yellow-800'
            : 'bg-red-100 text-red-800';

        // ── Mobile card ──
        const card = document.createElement('div');
        card.className = 'border border-gray-200 rounded-lg p-4 cursor-pointer hover:bg-gray-50 transition';
        card.onclick = () => {
            const detail = card.querySelector('.card-detail');
            if (detail) detail.classList.toggle('hidden');
        };
        card.innerHTML = `
            <div class="flex items-start justify-between mb-2">
                <div class="flex-1 min-w-0">
                    <p class="font-medium text-gray-900 text-sm">${esc(job.title || '')}</p>
                    <p class="text-gray-600 text-xs mt-0.5">${esc(job.company || '')}${job.location ? ' · ' + esc(job.location) : ''}</p>
                </div>
                <span class="inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${scoreBg} ml-2 shrink-0">${Number(score).toFixed(1)}</span>
            </div>
            <div class="flex items-center gap-2 text-xs text-gray-500 mb-2">
                ${level ? `<span class="bg-gray-100 px-1.5 py-0.5 rounded">${esc(level)}</span>` : ''}
                ${job.date_posted ? `<span>${esc(job.date_posted)}</span>` : ''}
            </div>
            <p class="text-xs text-gray-600 line-clamp-2">${esc(reasoning)}</p>
            <div class="card-detail hidden mt-3 pt-3 border-t border-gray-100 space-y-2 text-xs">
                <div><span class="font-medium text-gray-700">Cover Letter Hook:</span> <span class="text-gray-600">${esc(hook || 'N/A')}</span></div>
                <div><span class="font-medium text-gray-700">Matching Skills:</span> <span class="text-gray-600">${esc(matchingSkills || 'N/A')}</span></div>
                <div><span class="font-medium text-gray-700">Skill Gaps:</span> <span class="text-gray-600">${esc(gaps || 'None identified')}</span></div>
                ${job.url ? `<div><a href="${esc(job.url)}" target="_blank" rel="noopener" class="text-indigo-600 hover:underline">View Job Posting &rarr;</a></div>` : ''}
            </div>
        `;
        cards.appendChild(card);

        // ── Desktop table row ──
        const row = document.createElement('tr');
        row.className = 'border-b border-gray-100 hover:bg-gray-50 cursor-pointer';
        row.setAttribute('data-idx', idx);
        row.onclick = () => toggleExpandRow(idx);
        row.innerHTML = `
            <td class="px-3 py-3"><span class="inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${scoreBg}">${Number(score).toFixed(1)}</span></td>
            <td class="px-3 py-3 text-gray-600">${esc(level)}</td>
            <td class="px-3 py-3 font-medium text-gray-900 truncate" title="${esc(job.title || '')}">${esc(job.title || '')}</td>
            <td class="px-3 py-3 text-gray-700 truncate" title="${esc(job.company || '')}">${esc(job.company || '')}</td>
            <td class="px-3 py-3 text-gray-600 truncate" title="${esc(job.location || '')}">${esc(job.location || '')}</td>
            <td class="px-3 py-3 text-gray-500 text-xs whitespace-nowrap">${esc(job.date_posted || '—')}</td>
            <td class="px-3 py-3 text-gray-600 max-w-[200px] truncate" title="${esc(reasoning)}">${esc(reasoning)}</td>
            <td class="px-3 py-3 text-gray-600 max-w-[160px] truncate" title="${esc(hook)}">${esc(hook)}</td>
        `;
        body.appendChild(row);

        // Expandable detail row (hidden by default)
        const detail = document.createElement('tr');
        detail.id = `detail-${idx}`;
        detail.className = 'hidden';
        detail.innerHTML = `
            <td colspan="8" class="px-4 py-4 bg-gray-50">
                <div class="space-y-2 text-sm">
                    <div><span class="font-medium text-gray-700">Full Reasoning:</span> <span class="text-gray-600">${esc(reasoning || 'N/A')}</span></div>
                    <div><span class="font-medium text-gray-700">Cover Letter Hook:</span> <span class="text-gray-600">${esc(hook || 'N/A')}</span></div>
                    <div><span class="font-medium text-gray-700">Matching Skills:</span> <span class="text-gray-600">${esc(matchingSkills || 'N/A')}</span></div>
                    <div><span class="font-medium text-gray-700">Skill Gaps:</span> <span class="text-gray-600">${esc(gaps || 'None identified')}</span></div>
                    ${job.url ? `<div><a href="${esc(job.url)}" target="_blank" rel="noopener" class="text-indigo-600 hover:underline">View Job Posting &rarr;</a></div>` : ''}
                </div>
            </td>
        `;
        body.appendChild(detail);
    });

    container.classList.remove('hidden');
    updateSortArrows();
}

function toggleExpandRow(idx) {
    const detail = document.getElementById(`detail-${idx}`);
    if (detail) detail.classList.toggle('hidden');
}

function sortResults(column) {
    if (sortColumn === column) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        sortColumn = column;
        sortDirection = column === 'score' ? 'desc' : 'asc';
    }

    state.results.sort((a, b) => {
        let va = a[column] ?? '';
        let vb = b[column] ?? '';
        if (typeof va === 'number' && typeof vb === 'number') {
            return sortDirection === 'asc' ? va - vb : vb - va;
        }
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
        if (va < vb) return sortDirection === 'asc' ? -1 : 1;
        if (va > vb) return sortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    renderResults(state.results);
}

function updateSortArrows() {
    document.querySelectorAll('.sort-arrow').forEach(el => {
        const col = el.getAttribute('data-col');
        if (col === sortColumn) {
            el.textContent = sortDirection === 'asc' ? ' \u25B2' : ' \u25BC';
        } else {
            el.textContent = '';
        }
    });
}

// ── CSV Download ──────────────────────────────────────────────────────────────

function downloadCSV() {
    if (state.sessionId) {
        window.location.href = `/api/download-csv?session_id=${encodeURIComponent(state.sessionId)}`;
    } else {
        // Fallback: generate CSV client-side
        const headers = ['Score', 'Level', 'Title', 'Company', 'Location', 'Reasoning', 'Hook'];
        const rows = state.results.map(j => [
            j.score, j.level, j.title, j.company, j.location, j.reasoning, j.hook,
        ].map(v => `"${String(v || '').replace(/"/g, '""')}"`).join(','));
        const csv = [headers.join(','), ...rows].join('\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'ux-jobs-results.csv';
        a.click();
        URL.revokeObjectURL(url);
    }
}

// ── New Search ────────────────────────────────────────────────────────────────

function newSearch() {
    state.results = [];
    goToStep(2);
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function setLoading(btn, spinner, loading) {
    if (loading) {
        btn.disabled = true;
        spinner.classList.remove('hidden');
    } else {
        btn.disabled = false;
        spinner.classList.add('hidden');
    }
}

function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    showStep(1);
});
