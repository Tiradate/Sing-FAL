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
    const floorRoute = data.floorRoute || '/';
    const rotateStorageKey = 'dashboardAutoRotate';
    let rotateTimer = null;

    const startAutoRotate = () => {
      if (rotateTimer) {
        return;
      }
      rotateBtn.classList.remove('btn-outline-secondary');
      rotateBtn.classList.add('btn-success');
      rotateBtn.textContent = 'Stop';
      rotateTimer = setInterval(() => {
        const index = data.floors.indexOf(floorSelect.value);
        const nextIndex = (index + 1) % data.floors.length;
        floorSelect.value = data.floors[nextIndex];
        window.location = `${floorRoute}?floor=${data.floors[nextIndex]}`;
      }, (data.autoRotateSeconds || 10) * 1000);
      localStorage.setItem(rotateStorageKey, 'true');
    };

    const stopAutoRotate = () => {
      if (!rotateTimer) {
        return;
      }
      clearInterval(rotateTimer);
      rotateTimer = null;
      rotateBtn.classList.remove('btn-success');
      rotateBtn.classList.add('btn-outline-secondary');
      rotateBtn.textContent = 'Auto';
      localStorage.setItem(rotateStorageKey, 'false');
    };

    rotateBtn.addEventListener('click', () => {
      if (rotateTimer) {
        stopAutoRotate();
      } else {
        startAutoRotate();
      }
    });

    if (localStorage.getItem(rotateStorageKey) === 'true') {
      startAutoRotate();
    }

    floorSelect.addEventListener('change', (event) => {
      const floor = event.target.value;
      window.location = `${floorRoute}?floor=${floor}`;
    });
  }

  if (data.homeRoute) {
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        window.location = data.homeRoute;
      }
    });
  }
})();
