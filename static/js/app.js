/* MAN PesquisaVoos - Frontend Application */

const API = '';
let currentOffers = [];
let priceChart = null;

// ─── Init ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadOffers();
    loadHistory();
    loadConfig();

    document.getElementById('btn-refresh').addEventListener('click', triggerSearch);
    document.getElementById('btn-config-toggle').addEventListener('click', toggleConfig);
    document.getElementById('btn-save-config').addEventListener('click', saveConfig);
    document.getElementById('btn-new-search').addEventListener('click', saveConfigAndSearch);
    document.getElementById('filter-sort').addEventListener('change', loadOffers);
    document.getElementById('filter-max-price').addEventListener('change', loadOffers);
    document.getElementById('filter-airline').addEventListener('change', loadOffers);
    document.getElementById('filter-airport').addEventListener('change', loadOffers);
    document.getElementById('filter-stops').addEventListener('change', loadOffers);
    document.getElementById('filter-confidence').addEventListener('change', loadOffers);

    // Auto-refresh status every 30s
    setInterval(loadStatus, 30000);
});

// ─── API Calls ───────────────────────────────────────────────────
async function apiGet(path) {
    const resp = await fetch(`${API}${path}`);
    return resp.json();
}

async function apiPost(path, data) {
    const resp = await fetch(`${API}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: data ? JSON.stringify(data) : undefined,
    });
    return resp.json();
}

// ─── Load Status ─────────────────────────────────────────────────
async function loadStatus() {
    try {
        const data = await apiGet('/api/status');
        const el = document.getElementById('last-update');
        const dot = document.getElementById('status-dot');

        if (data.search_locked) {
            el.textContent = 'Buscando...';
            dot.className = 'status-dot running';
            document.getElementById('btn-refresh').disabled = true;
        } else if (data.last_run) {
            const dt = data.last_run.finished_at || data.last_run.started_at;
            el.textContent = formatDateTime(dt);
            dot.className = 'status-dot ok';
            document.getElementById('btn-refresh').disabled = false;

            if (data.last_run.status === 'running') {
                dot.className = 'status-dot running';
                el.textContent = 'Busca em andamento...';
                document.getElementById('btn-refresh').disabled = true;
                // Poll more frequently while running
                setTimeout(() => { loadStatus(); loadOffers(); }, 5000);
            }
        } else {
            el.textContent = 'Nenhuma busca realizada';
            dot.className = 'status-dot error';
            document.getElementById('btn-refresh').disabled = false;
        }
    } catch (e) {
        console.error('Status error:', e);
    }
}

// ─── Load Offers ─────────────────────────────────────────────────
async function loadOffers() {
    const params = new URLSearchParams();
    const sort = document.getElementById('filter-sort').value;
    const maxPrice = document.getElementById('filter-max-price').value;
    const airline = document.getElementById('filter-airline').value;
    const airport = document.getElementById('filter-airport').value;
    const stops = document.getElementById('filter-stops').value;
    const confidence = document.getElementById('filter-confidence').checked;

    if (sort) params.set('sort', sort);
    if (maxPrice) params.set('max_price', maxPrice);
    if (airline) params.set('airline', airline);
    if (airport) params.set('origin_airport', airport);
    if (stops !== '') params.set('max_stops', stops);
    if (confidence) params.set('hide_low_confidence', '1');

    try {
        const data = await apiGet(`/api/offers?${params}`);
        currentOffers = data.offers || [];
        renderOffers(data);
        updateSummary(data);
    } catch (e) {
        console.error('Offers error:', e);
        document.getElementById('offers-list').innerHTML =
            '<div class="empty-state"><h3>Erro ao carregar ofertas</h3><p>Tente novamente em alguns instantes.</p></div>';
    }
}

// ─── Render Offers ───────────────────────────────────────────────
function renderOffers(data) {
    const container = document.getElementById('offers-list');
    const countEl = document.getElementById('offers-count');
    const offers = data.offers || [];

    if (!offers.length) {
        container.innerHTML = `
            <div class="empty-state">
                <h3>Nenhuma oferta encontrada</h3>
                <p>Configure a chave SERPAPI_KEY e clique em "Atualizar" para buscar voos.</p>
                <p style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-secondary)">
                    Consulte o README para instruções de configuração.
                </p>
            </div>`;
        countEl.textContent = '';
        return;
    }

    countEl.textContent = `${offers.length} oferta(s) encontrada(s)`;
    container.innerHTML = offers.map((o, i) => renderOfferCard(o, i)).join('');

    // Attach click events
    container.querySelectorAll('.offer-main').forEach(el => {
        el.addEventListener('click', () => {
            const details = el.parentElement.querySelector('.offer-details');
            details.classList.toggle('visible');
        });
    });
}

function renderOfferCard(o, index) {
    const badges = parseBadges(o.badges);
    const badgeHtml = badges.map(b => `<span class="badge ${badgeClass(b)}">${b}</span>`).join('');

    const priceChangeHtml = renderPriceChange(o.price_change, o.price_change_pct);
    const confClass = (o.confidence_level || 'Médio').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const highlighted = badges.includes('Mais Barata') ? 'highlighted' : '';

    return `
    <div class="offer-card ${highlighted}">
        <div class="offer-main">
            <div class="offer-routes">
                <div class="offer-route">
                    <span class="route-label">Ida</span>
                    <span class="route-time">${o.outbound_time || '--:--'}</span>
                    <span class="route-airports">${o.outbound_origin}</span>
                    <span class="route-arrow">&rarr;</span>
                    <span class="route-time">${o.outbound_arrival_time || '--:--'}</span>
                    <span class="route-airports">${o.outbound_destination}</span>
                    <span class="route-stops">${o.outbound_stops === 0 ? 'Direto' : o.outbound_stops + ' parada(s)'}</span>
                    <span class="route-meta">${formatDuration(o.outbound_duration_minutes)}</span>
                </div>
                <div class="offer-route">
                    <span class="route-label">Volta</span>
                    <span class="route-time">${o.inbound_time || '--:--'}</span>
                    <span class="route-airports">${o.inbound_origin}</span>
                    <span class="route-arrow">&rarr;</span>
                    <span class="route-time">${o.inbound_arrival_time || '--:--'}</span>
                    <span class="route-airports">${o.inbound_destination}</span>
                    <span class="route-stops">${o.inbound_stops === 0 ? 'Direto' : o.inbound_stops + ' parada(s)'}</span>
                    <span class="route-meta">${formatDuration(o.inbound_duration_minutes)}</span>
                </div>
            </div>
            <div class="offer-price">
                <span class="total">${formatCurrency(o.price_total, o.currency)}</span>
                <span class="per-person">${formatCurrency(o.price_per_person, o.currency)}/pessoa</span>
                ${priceChangeHtml}
            </div>
        </div>
        ${badgeHtml ? `<div class="offer-badges">${badgeHtml}</div>` : ''}
        <div class="offer-footer">
            <div class="offer-footer-left">
                <span>${o.operating_airline || 'N/A'}</span>
                <span>via ${o.seller || o.source || 'N/A'}</span>
                <span class="confidence ${confClass}"><span class="conf-dot"></span> ${o.confidence_level || 'Médio'}</span>
                <span>${o.outbound_date} &mdash; ${o.inbound_date}</span>
            </div>
            ${o.booking_url ? `<a href="${o.booking_url}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">Ver Oferta</a>` : ''}
        </div>
        <div class="offer-details" id="details-${index}">
            <div class="details-grid">
                <div class="detail-item"><label>Aeroporto Ida</label><span>${o.outbound_origin} &rarr; ${o.outbound_destination}</span></div>
                <div class="detail-item"><label>Data/Hora Ida</label><span>${o.outbound_date} ${o.outbound_time || ''}</span></div>
                <div class="detail-item"><label>Chegada Ida</label><span>${o.outbound_arrival_date || ''} ${o.outbound_arrival_time || ''}</span></div>
                <div class="detail-item"><label>Duração Ida</label><span>${formatDuration(o.outbound_duration_minutes)}</span></div>
                <div class="detail-item"><label>Paradas Ida</label><span>${o.outbound_stops} ${o.outbound_connections ? '(' + o.outbound_connections + ')' : ''}</span></div>
                <div class="detail-item"><label>Cias. Ida</label><span>${o.outbound_airlines || 'N/A'}</span></div>
                <div class="detail-item"><label>Aeroporto Volta</label><span>${o.inbound_origin} &rarr; ${o.inbound_destination}</span></div>
                <div class="detail-item"><label>Data/Hora Volta</label><span>${o.inbound_date} ${o.inbound_time || ''}</span></div>
                <div class="detail-item"><label>Chegada Volta</label><span>${o.inbound_arrival_date || ''} ${o.inbound_arrival_time || ''}</span></div>
                <div class="detail-item"><label>Duração Volta</label><span>${formatDuration(o.inbound_duration_minutes)}</span></div>
                <div class="detail-item"><label>Paradas Volta</label><span>${o.inbound_stops} ${o.inbound_connections ? '(' + o.inbound_connections + ')' : ''}</span></div>
                <div class="detail-item"><label>Cias. Volta</label><span>${o.inbound_airlines || 'N/A'}</span></div>
                <div class="detail-item"><label>Companhia Operadora</label><span>${o.operating_airline || 'N/A'}</span></div>
                <div class="detail-item"><label>Vendedor/Agência</label><span>${o.seller || 'N/A'}</span></div>
                <div class="detail-item"><label>Fonte</label><span>${o.source || 'N/A'}</span></div>
                <div class="detail-item"><label>Bagagem</label><span>${o.baggage_info || 'Consultar no site'}</span></div>
                <div class="detail-item"><label>Regras Tarifárias</label><span>${o.fare_rules || 'Consultar no site'}</span></div>
                <div class="detail-item"><label>Confiabilidade</label><span class="confidence ${confClass}"><span class="conf-dot"></span> ${o.confidence_level}</span></div>
                <div class="detail-item"><label>Coletado em</label><span>${formatDateTime(o.collected_at)}</span></div>
                ${o.notes ? `<div class="detail-item"><label>Observações</label><span>${o.notes}</span></div>` : ''}
            </div>
            <div style="margin-top:1rem; display:flex; gap:0.5rem;">
                ${o.booking_url ? `<a href="${o.booking_url}" target="_blank" rel="noopener" class="btn btn-success btn-sm">Acessar Oferta</a>` : ''}
                <button class="btn btn-outline btn-sm" onclick="showOfferHistory('${o.offer_hash}')">Ver Histórico de Preço</button>
            </div>
        </div>
    </div>`;
}

// ─── Summary ─────────────────────────────────────────────────────
function updateSummary(data) {
    const offers = data.offers || [];
    const bestPriceEl = document.getElementById('summary-best-price');
    const bestValueEl = document.getElementById('summary-best-value');
    const bestReliableEl = document.getElementById('summary-reliable');
    const trendEl = document.getElementById('summary-trend');

    if (!offers.length) {
        bestPriceEl.textContent = '--';
        bestValueEl.textContent = '--';
        bestReliableEl.textContent = '--';
        trendEl.textContent = '--';
        return;
    }

    // Best price
    const cheapest = offers.reduce((a, b) => a.price_total < b.price_total ? a : b);
    bestPriceEl.textContent = formatCurrency(cheapest.price_total, cheapest.currency);
    document.getElementById('summary-best-price-detail').textContent =
        `${cheapest.operating_airline || 'N/A'} via ${cheapest.seller || cheapest.source}`;

    // Best value (has badge)
    const bestValue = offers.find(o => {
        const badges = parseBadges(o.badges);
        return badges.includes('Melhor Custo-Benefício');
    }) || cheapest;
    bestValueEl.textContent = formatCurrency(bestValue.price_total, bestValue.currency);
    document.getElementById('summary-best-value-detail').textContent =
        `${bestValue.operating_airline || 'N/A'} - ${bestValue.confidence_level}`;

    // Most reliable
    const reliable = offers.filter(o => o.confidence_level === 'Alto');
    if (reliable.length) {
        const best = reliable.reduce((a, b) => a.price_total < b.price_total ? a : b);
        bestReliableEl.textContent = best.operating_airline || best.seller || 'N/A';
        document.getElementById('summary-reliable-detail').textContent =
            formatCurrency(best.price_total, best.currency);
    } else {
        bestReliableEl.textContent = offers[0].operating_airline || 'N/A';
        document.getElementById('summary-reliable-detail').textContent = 'Confiança média';
    }

    // Trend
    const changes = offers.filter(o => o.price_change !== null);
    if (changes.length) {
        const avgChange = changes.reduce((sum, o) => sum + (o.price_change || 0), 0) / changes.length;
        if (avgChange < -50) {
            trendEl.innerHTML = '<span class="price-change down">&#9660; Caindo</span>';
        } else if (avgChange > 50) {
            trendEl.innerHTML = '<span class="price-change up">&#9650; Subindo</span>';
        } else {
            trendEl.innerHTML = '<span class="price-change stable">&#9654; Estável</span>';
        }
        document.getElementById('summary-trend-detail').textContent =
            `Média: ${avgChange > 0 ? '+' : ''}${formatCurrency(avgChange, 'BRL')}`;
    } else {
        trendEl.textContent = 'Sem dados';
        document.getElementById('summary-trend-detail').textContent = 'Primeira coleta';
    }
}

// ─── Price History Chart ─────────────────────────────────────────
async function loadHistory() {
    try {
        const data = await apiGet('/api/history?days=30');
        renderChart(data);
    } catch (e) {
        console.error('History error:', e);
    }
}

function renderChart(data) {
    const ctx = document.getElementById('price-chart');
    if (!ctx) return;

    if (!data || !data.length) {
        ctx.parentElement.innerHTML = '<p style="text-align:center;color:var(--text-secondary);padding:2rem">Histórico será exibido após a primeira coleta</p>';
        return;
    }

    const sorted = [...data].sort((a, b) => a.collected_date.localeCompare(b.collected_date));
    const labels = sorted.map(d => {
        const parts = d.collected_date.split('-');
        return `${parts[2]}/${parts[1]}`;
    });

    if (priceChart) priceChart.destroy();

    priceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Menor Preço',
                    data: sorted.map(d => d.min_price),
                    borderColor: '#059669',
                    backgroundColor: 'rgba(5,150,105,0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 4,
                },
                {
                    label: 'Preço Médio',
                    data: sorted.map(d => Math.round(d.avg_price)),
                    borderColor: '#2563eb',
                    borderDash: [5, 5],
                    tension: 0.3,
                    pointRadius: 3,
                },
                {
                    label: 'Maior Preço',
                    data: sorted.map(d => d.max_price),
                    borderColor: '#dc2626',
                    backgroundColor: 'rgba(220,38,38,0.05)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: R$ ${ctx.parsed.y.toLocaleString('pt-BR')}`,
                    },
                },
            },
            scales: {
                y: {
                    ticks: {
                        callback: (v) => `R$ ${(v/1000).toFixed(0)}k`,
                    },
                },
            },
        },
    });
}

async function showOfferHistory(hash) {
    try {
        const data = await apiGet(`/api/history?offer_hash=${hash}`);
        if (!data.length) {
            alert('Nenhum histórico disponível para esta oferta.');
            return;
        }
        // Simple display in alert for now
        const lines = data.map(d => `${d.collected_date}: R$ ${d.price_total.toLocaleString('pt-BR')}`);
        alert('Histórico de preço:\n\n' + lines.join('\n'));
    } catch (e) {
        console.error(e);
    }
}

// ─── Config ──────────────────────────────────────────────────────
async function loadConfig() {
    try {
        const config = await apiGet('/api/config');
        if (!config) return;

        setValue('config-origin', config.origin_airports);
        setValue('config-destination', config.destination_airports);
        setValue('config-return-origin', config.return_origin_airports);
        setValue('config-departure', config.departure_date);
        setValue('config-return', config.return_date);
        setValue('config-passengers', config.passengers);
        setValue('config-flexibility', config.flexibility_days);
    } catch (e) {
        console.error('Config error:', e);
    }
}

function setValue(id, val) {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.value = val;
}

function toggleConfig() {
    document.getElementById('config-panel').classList.toggle('visible');
}

async function saveConfig() {
    const data = {
        origin_airports: document.getElementById('config-origin').value,
        destination_airports: document.getElementById('config-destination').value,
        return_origin_airports: document.getElementById('config-return-origin').value,
        departure_date: document.getElementById('config-departure').value,
        return_date: document.getElementById('config-return').value,
        passengers: parseInt(document.getElementById('config-passengers').value) || 4,
        flexibility_days: parseInt(document.getElementById('config-flexibility').value) || 3,
    };
    try {
        await apiPost('/api/config', data);
        toggleConfig();
    } catch (e) {
        alert('Erro ao salvar configuração.');
    }
}

async function saveConfigAndSearch() {
    await saveConfig();
    await triggerSearch();
}

// ─── Search ──────────────────────────────────────────────────────
async function triggerSearch() {
    const btn = document.getElementById('btn-refresh');
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> Buscando...';

    try {
        const resp = await apiPost('/api/search');
        if (resp.status === 'already_running') {
            alert('Uma busca já está em andamento. Aguarde.');
        }
        // Poll for completion
        pollSearch();
    } catch (e) {
        alert('Erro ao iniciar busca.');
        btn.disabled = false;
        btn.innerHTML = 'Atualizar';
    }
}

function pollSearch() {
    const poll = setInterval(async () => {
        const status = await apiGet('/api/status');
        if (!status.search_locked) {
            clearInterval(poll);
            document.getElementById('btn-refresh').disabled = false;
            document.getElementById('btn-refresh').innerHTML = 'Atualizar';
            loadOffers();
            loadHistory();
            loadStatus();
        }
    }, 3000);
}

// ─── Helpers ─────────────────────────────────────────────────────
function formatCurrency(val, currency) {
    if (val === null || val === undefined) return '--';
    const cur = currency || 'BRL';
    try {
        return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: cur }).format(val);
    } catch {
        return `R$ ${Number(val).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
    }
}

function formatDuration(minutes) {
    if (!minutes) return '--';
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return `${h}h${m > 0 ? m + 'min' : ''}`;
}

function formatDateTime(dt) {
    if (!dt) return '--';
    try {
        const d = new Date(dt + (dt.includes('T') ? '' : 'T00:00:00'));
        return d.toLocaleString('pt-BR', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    } catch {
        return dt;
    }
}

function parseBadges(badges) {
    if (!badges) return [];
    if (Array.isArray(badges)) return badges;
    try { return JSON.parse(badges); } catch { return []; }
}

function badgeClass(badge) {
    const map = {
        'Mais Barata': 'badge-best-price',
        'Melhor Custo-Benefício': 'badge-best-value',
        'Menor Tempo de Viagem': 'badge-fastest',
        'Mais Confiável': 'badge-reliable',
    };
    return map[badge] || 'badge-warning';
}

function renderPriceChange(change, pct) {
    if (change === null || change === undefined) return '';
    if (Math.abs(change) < 10) {
        return '<span class="price-change stable">&#9654; estável</span>';
    }
    if (change < 0) {
        return `<span class="price-change down">&#9660; ${formatCurrency(Math.abs(change), 'BRL')} (${Math.abs(pct)}%)</span>`;
    }
    return `<span class="price-change up">&#9650; +${formatCurrency(change, 'BRL')} (+${pct}%)</span>`;
}
