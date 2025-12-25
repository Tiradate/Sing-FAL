(function () {
  const data = window.dashboardData || {};

  const dailyCtx = document.getElementById('dailyChart');
  if (dailyCtx && data.dailyLabels) {
    new Chart(dailyCtx, {
      type: 'line',
      data: {
        labels: data.dailyLabels,
        datasets: [{
          label: 'PM2.5',
          data: data.dailyValues,
          borderColor: '#0d6efd',
          backgroundColor: 'rgba(13, 110, 253, 0.1)',
          fill: true,
          tension: 0.3,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      }
    });
  }

  const weeklyCtx = document.getElementById('weeklyChart');
  if (weeklyCtx && data.weeklyLabels) {
    new Chart(weeklyCtx, {
      type: 'bar',
      data: {
        labels: data.weeklyLabels,
        datasets: [{
          label: 'PM2.5',
          data: data.weeklyValues,
          backgroundColor: '#198754',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      }
    });
  }

  const floorSelect = document.getElementById('floorSelect');
  const rotateBtn = document.getElementById('floorRotate');
  if (floorSelect && rotateBtn && data.floors) {
    const floorValues = data.floors.map((floor) => `${floor}`);
    const floorRoute = data.floorRoute || '/';
    let rotateTimer = null;
    const storageKey = 'autoRotateEnabled';
    const setAutoState = (enabled) => {
      if (!window.localStorage) {
        return;
      }
      if (enabled) {
        window.localStorage.setItem(storageKey, 'true');
      } else {
        window.localStorage.removeItem(storageKey);
      }
    };
    const isAutoEnabled = () => window.localStorage && window.localStorage.getItem(storageKey) === 'true';
    const updateButtonState = (enabled) => {
      if (enabled) {
        rotateBtn.classList.remove('btn-outline-secondary');
        rotateBtn.classList.add('btn-success');
        rotateBtn.textContent = 'Stop';
      } else {
        rotateBtn.classList.remove('btn-success');
        rotateBtn.classList.add('btn-outline-secondary');
        rotateBtn.textContent = 'Auto';
      }
    };
    const stopAutoRotate = () => {
      if (rotateTimer) {
        clearInterval(rotateTimer);
        rotateTimer = null;
      }
      setAutoState(false);
      updateButtonState(false);
    };
    const startAutoRotate = () => {
      if (rotateTimer || floorValues.length === 0) {
        return;
      }
      updateButtonState(true);
      setAutoState(true);
      rotateTimer = setInterval(() => {
        const currentFloor = `${floorSelect.value}`;
        let index = floorValues.indexOf(currentFloor);
        if (index === -1) {
          index = 0;
        }
        const nextIndex = (index + 1) % floorValues.length;
        const nextFloor = floorValues[nextIndex];
        floorSelect.value = nextFloor;
        window.location = `${floorRoute}?floor=${nextFloor}`;
      }, (data.autoRotateSeconds || 10) * 1000);
    };
    rotateBtn.addEventListener('click', () => {
      if (rotateTimer) {
        stopAutoRotate();
        return;
      }
      startAutoRotate();
    });
    floorSelect.addEventListener('change', (event) => {
      const floor = event.target.value;
      window.location = `${floorRoute}?floor=${floor}`;
    });
    if (isAutoEnabled()) {
      startAutoRotate();
    } else {
      updateButtonState(false);
    }
  }

  if (data.homeRoute) {
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        window.location = data.homeRoute;
      }
    });
  }
})();
