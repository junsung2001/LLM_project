// app.js

// =============================
// 1. 지도 관련 전역 상태
// =============================
let map = null;
let mapMarkers = [];
let cityList = []; // /cities 에서 받아오는 도시 정보들 저장


// =============================
// 2. 지도 렌더링 함수
// =============================
function renderMapForPlan(draft) {
  const mapEl = document.getElementById('map');
  console.log('지도 요청 들어옴. draft:', draft);

  if (!mapEl) {
    console.warn('#map 요소를 찾을 수 없습니다.');
    return;
  }

  // 안내 문구는 "지도 최초 렌더 전에만"
  if (!map) {
    mapEl.innerHTML = '<p class="text-xs text-gray-500 p-2">지도를 준비하는 중입니다.</p>';
  }

  if (!draft || !draft.itinerary) {
    mapEl.innerHTML = '<p class="text-xs text-red-500 p-2">이 플랜에 itinerary 데이터가 없습니다.</p>';
    return;
  }

  const points = [];
  Object.values(draft.itinerary).forEach(items => {
    (items || []).forEach(it => {
      if (typeof it.lat === 'number' && typeof it.lng === 'number') {
        points.push({
          lat: it.lat,
          lng: it.lng,
          name: it.name,
          slot: it.slot
        });
      }
    });
  });

  if (points.length === 0) {
    mapEl.innerHTML = '<p class="text-xs text-red-500 p-2">이 플랜에는 좌표 정보가 없습니다.<br/>• 백엔드에서 GOOGLE_MAPS_API_KEY가 설정됐는지<br/>• /plan 응답에 lat/lng가 포함되는지 확인하세요.</p>';
    return;
  }

  if (!window.google || !google.maps) {
    mapEl.innerHTML = '<p class="text-xs text-red-500 p-2">Google Maps JS가 로드되지 않았습니다. 스크립트 키를 확인하세요.</p>';
    console.error('google.maps 가 정의되지 않았습니다.');
    return;
  }

  const center = { lat: points[0].lat, lng: points[0].lng };

  //  첫 렌더일 때만 innerHTML 비우고 새로 map 생성
  if (!map) {
    mapEl.innerHTML = '';
    map = new google.maps.Map(mapEl, {
      center,
      zoom: 13
    });
  } else {
    // 이미 만들어진 map은 center/zoom만 변경
    map.setCenter(center);
    map.setZoom(13);
  }

  // 기존 마커 제거
  mapMarkers.forEach(m => m.setMap(null));
  mapMarkers = [];

  // 새 마커 추가
  points.forEach(p => {
    const marker = new google.maps.Marker({
      map,
      position: { lat: p.lat, lng: p.lng },
      title: `${p.slot} · ${p.name}`
    });
    mapMarkers.push(marker);
  });

  console.log('지도 렌더 완료, 마커 개수:', mapMarkers.length);
}


// =============================
// 3. DOMContentLoaded 이후 앱 로직
// =============================
document.addEventListener('DOMContentLoaded', () => {
  const envBadge = document.getElementById('env-badge');
  const form = document.getElementById('plan-form');
  const loading = document.getElementById('loading');
  const narrativeEl = document.getElementById('narrative');
  const itineraryEl = document.getElementById('itinerary');

  const backendInput = document.getElementById('backend');
  const cityInput = document.getElementById('city');

  // -----------------------------
  // 3-1. health 체크
  // -----------------------------
  async function checkHealth(base) {
    try {
      const r = await fetch(new URL('/health', base), { mode: 'cors' });
      if (!r.ok) throw new Error('bad');
      const j = await r.json();
      const llmText = j.llm ? 'LLM 사용' : 'LLM 미사용';
      const mapsText = j.maps ? ' · Maps OK' : '';
      envBadge.textContent = `서버 OK · ${llmText}${mapsText}`;
      envBadge.className = 'ml-auto inline-flex items-center text-xs rounded-full px-2 py-1 bg-emerald-50 text-emerald-700';
    } catch {
      envBadge.textContent = '백엔드 미확인';
      envBadge.className = 'ml-auto inline-flex items-center text-xs rounded-full px-2 py-1 bg-gray-100 text-gray-600';
    }
  }

  // -----------------------------
  // 3-2. narrative 렌더링
  // -----------------------------
  function renderNarrative(text) {
    if (!text) {
      narrativeEl.innerHTML = '';
      return;
    }
    const safe = text
      .replace(/\n/g, '<br/>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    narrativeEl.innerHTML = safe;
  }

  // -----------------------------
  // 3-3. 도시 datalist 옵션 갱신
  // -----------------------------
  function updateCityOptions(cities) {
    cityList = cities || [];

    const dataList = document.getElementById('city-options');
    if (!dataList) return;

    dataList.innerHTML = '';

    cityList.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.code;        // 입력값
      opt.textContent = c.label; // 한글 라벨
      dataList.appendChild(opt);
    });
  }

  // -----------------------------
  // 3-4. 도시 소개 카드 렌더링
  // -----------------------------
  function renderCityInfo(cityCode, backendBase) {
    const infoBox = document.getElementById('city-info');
    const labelEl = document.getElementById('city-info-label');
    const descEl = document.getElementById('city-info-desc');
    const codeEl = document.getElementById('city-info-code');
    const imgEl = document.getElementById('city-info-image');

    if (!infoBox) return;

    const city = cityList.find(c => c.code === cityCode);
    if (!city) {
      // 지원 목록에 없는 도시 → 카드 숨김
      infoBox.classList.add('hidden');
      return;
    }

    infoBox.classList.remove('hidden');
    codeEl.textContent = city.code;
    labelEl.textContent = city.label || city.code;
    descEl.textContent = city.description || '';

    if (city.image_path) {
      try {
        const imgUrl = new URL(city.image_path, backendBase).toString();
        imgEl.src = imgUrl;
        imgEl.classList.remove('hidden');
      } catch (e) {
        console.warn('이미지 URL 생성 실패:', e);
        imgEl.classList.add('hidden');
      }
    } else {
      imgEl.classList.add('hidden');
    }
  }

  // -----------------------------
  // 3-5. /cities 호출 (도시 목록 + 카드 초기화)
  // -----------------------------
  async function loadCities(base) {
    try {
      const url = new URL('/cities', base);
      const r = await fetch(url, { mode: 'cors' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      console.log('도시 목록:', j);
      updateCityOptions(j.cities);

      // 현재 입력된 city에 맞춰 카드도 초기 렌더
      if (cityInput && cityInput.value) {
        renderCityInfo(cityInput.value.trim(), base);
      }
    } catch (err) {
      console.warn('도시 목록을 불러오지 못했습니다:', err);
    }
  }

  // -----------------------------
  // 3-6. 일정(itinerary) 렌더링
  // -----------------------------
  function buildItineraryElement(draft) {
    const container = document.createElement('div');
    if (!draft || !draft.itinerary) return container;

    Object.entries(draft.itinerary).forEach(([day, items]) => {
      const card = document.createElement('div');
      card.className = 'rounded-xl border border-gray-200 my-3';

      const head = document.createElement('div');
      head.className = 'px-4 py-3 bg-gray-50 flex items-center justify-between';
      head.innerHTML = `<span class="font-medium">${day}</span><span class="text-xs text-gray-500">${(items || []).length} spots</span>`;

      const body = document.createElement('div');
      body.className = 'relative timeline px-4 py-4';

      (items || []).forEach((it, idx) => {
        const row = document.createElement('div');
        row.className = 'pl-8 mb-4 relative';
        row.innerHTML = `
          <div class="absolute left-2 top-1 w-3 h-3 rounded-full ${idx === 0 ? 'bg-indigo-600' : 'bg-gray-300'}"></div>
          <div class="flex items-center gap-2">
            <span class="text-xs inline-flex items-center px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700">${it.slot}</span>
            <span class="font-medium">${it.name}</span>
          </div>
          <div class="text-xs text-gray-600 mt-1">
            체류 ${it.eta_min ?? '-'}분 · 도보 ${it.walk_min ?? '-'}분 · 가격대 ${it.price ?? '-'} · 태그 ${Array.isArray(it.tags) ? it.tags.join(', ') : ''}
          </div>
          ${it.notes ? `<div class="text-xs text-gray-500 mt-1">💡 ${it.notes}</div>` : ''}
          ${it.maps_url ? `<a href="${it.maps_url}" target="_blank" class="text-xs text-indigo-600 hover:underline mt-1 inline-block">Google Maps에서 보기</a>` : ''}
        `;
        body.appendChild(row);
      });

      card.appendChild(head);
      card.appendChild(body);
      container.appendChild(card);
    });

    return container;
  }

  function renderPlans(data) {
    itineraryEl.innerHTML = '';
    if (!data || !Array.isArray(data.plans) || data.plans.length === 0) {
      itineraryEl.innerHTML = '<p class="text-sm text-gray-500">생성된 일정이 없습니다.</p>';
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'space-y-6';

    data.plans.forEach(plan => {
      const card = document.createElement('div');
      card.className = 'border border-gray-200 rounded-2xl p-4';

      const header = document.createElement('div');
      header.className = 'flex items-center justify-between mb-2';
      header.innerHTML = `
        <div>
          <div class="text-sm font-semibold">플랜 ${plan.id}</div>
          ${plan.summary && plan.summary.for_who ? `<div class="text-xs text-gray-600 mt-0.5">${plan.summary.for_who}</div>` : ''}
        </div>
      `;

      const mapBtn = document.createElement('button');
      mapBtn.className = 'text-xs px-2 py-1 rounded-lg bg-indigo-50 text-indigo-700 hover:bg-indigo-100';
      mapBtn.textContent = '이 플랜을 지도에서 보기';
      mapBtn.addEventListener('click', () => {
        console.log('지도 버튼 클릭, 플랜:', plan.id);
        renderMapForPlan(plan.draft);
      });

      header.appendChild(mapBtn);
      card.appendChild(header);

      if (plan.summary && (plan.summary.highlights || plan.summary.warnings)) {
        const summaryBox = document.createElement('div');
        summaryBox.className = 'bg-indigo-50 border border-indigo-100 rounded-xl p-3 mb-3 text-xs text-gray-800';
        const highlights = (plan.summary.highlights || []).map(h => `<li>🌟 ${h}</li>`).join('');
        const warnings = (plan.summary.warnings || []).map(w => `<li>⚠️ ${w}</li>`).join('');
        summaryBox.innerHTML = `
          <div class="font-semibold mb-1">요약/포인트</div>
          ${highlights ? `<ul class="mb-1">${highlights}</ul>` : ''}
          ${warnings ? `<ul>${warnings}</ul>` : ''}
        `;
        card.appendChild(summaryBox);
      }

      const itinEl = buildItineraryElement(plan.draft);
      card.appendChild(itinEl);

      wrapper.appendChild(card);
    });

    itineraryEl.appendChild(wrapper);

    // 첫 번째 플랜을 자동으로 지도에 표시
    if (data.plans && data.plans.length > 0) {
      renderMapForPlan(data.plans[0].draft);
    }
  }

  // -----------------------------
  // 3-7. /plan 요청
  // -----------------------------
  async function requestPlan(payload) {
    const base = backendInput.value.trim();
    const url = new URL('/plan', base);
    loading.classList.remove('hidden');
    narrativeEl.innerHTML = '';
    itineraryEl.innerHTML = '';
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        mode: 'cors'
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`HTTP ${r.status} - ${text}`);
      }
      const j = await r.json();
      if (j.plans && j.plans.length > 0) {
        renderNarrative(j.plans[0].narrative || j.narrative);
      } else {
        renderNarrative(j.narrative);
      }
      renderPlans(j);
    } catch (err) {
      renderNarrative(`요청 실패: ${err.message}.<br/>브라우저 콘솔을 확인하고, CORS 또는 백엔드 URL을 점검하세요.`);
    } finally {
      loading.classList.add('hidden');
    }
  }

  // -----------------------------
  // 3-8. 이벤트 리스너 등록
  // -----------------------------

  // 폼 제출 → /plan 호출
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const payload = {
      city: (document.getElementById('city').value || '').trim() || 'osaka',
      days: Number(document.getElementById('days').value || 2),
      interests: (document.getElementById('interests').value || '')
        .split(',')
        .map(s => s.trim())
        .filter(Boolean),
      with_kids: document.getElementById('with_kids').checked,
      budget: document.getElementById('budget').value,
      max_walk_min: Number(document.getElementById('max_walk_min').value || 20),
      travel_style: document.getElementById('travel_style').value,
      num_plans: Number(document.getElementById('num_plans').value || 1),
      with_summary: true
    };
    requestPlan(payload);
  });

  // 예시 버튼: 오사카
  document.getElementById('quick-osaka').addEventListener('click', () => {
    document.getElementById('city').value = 'osaka';
    document.getElementById('interests').value = '야경, 먹거리, 카페';
    document.getElementById('days').value = 2;
    document.getElementById('max_walk_min').value = 20;
    document.getElementById('travel_style').value = 'mixed';

    const base = backendInput.value.trim();
    renderCityInfo('osaka', base);
  });

  // 예시 버튼: 서울
  document.getElementById('quick-seoul').addEventListener('click', () => {
    document.getElementById('city').value = 'seoul';
    document.getElementById('interests').value = '전망, 사진, 먹거리';
    document.getElementById('days').value = 2;
    document.getElementById('max_walk_min').value = 20;
    document.getElementById('travel_style').value = 'sightseeing';

    const base = backendInput.value.trim();
    renderCityInfo('seoul', base);
  });

  // backend URL 변경 시 health + 도시 목록 다시 로드
  backendInput.addEventListener('change', () => {
    const base = backendInput.value.trim();
    checkHealth(base);
    loadCities(base);

    if (cityInput && cityInput.value) {
      renderCityInfo(cityInput.value.trim(), base);
    }
  });

  // 도시 입력 변경 시 도시 카드 갱신
  if (cityInput) {
    cityInput.addEventListener('change', () => {
      const base = backendInput.value.trim();
      renderCityInfo(cityInput.value.trim(), base);
    });
    cityInput.addEventListener('blur', () => {
      const base = backendInput.value.trim();
      renderCityInfo(cityInput.value.trim(), base);
    });
  }

  // -----------------------------
  // 3-9. 초기 실행
  // -----------------------------
  const initialBase = backendInput.value.trim();
  checkHealth(initialBase);
  loadCities(initialBase);
  if (cityInput && cityInput.value) {
    renderCityInfo(cityInput.value.trim(), initialBase);
  }
});
