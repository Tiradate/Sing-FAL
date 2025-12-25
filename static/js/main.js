(function () {
  const data = window.dashboardData || {};
  const metricOptions = data.metricOptions || {};

  const formatMetricLabel = (metricKey) => {
    const meta = metricOptions[metricKey];
    if (!meta) {
      return metricKey;
    }
    if (meta.unit) {
      return `${meta.label} (${meta.unit})`;
    }
    return meta.label;
  };

  const fetchSeries = async (route, metricKey) => {
    if (!route) {
      return null;
    }
    const params = new URLSearchParams({ format: 'json', metric: metricKey });
    if (data.activeFloor) {
      params.set('floor', data.activeFloor);
    }
    const response = await fetch(`${route}?${params.toString()}`);
    if (!response.ok) {
      return null;
    }
    return response.json();
  };

  const dailyCtx = document.getElementById('dailyChart');
  const dailyMetricSelect = document.getElementById('dailyMetricSelect');
  let dailyChart = null;
  if (dailyCtx && data.dailyLabels) {
    dailyChart = new Chart(dailyCtx, {
      type: 'line',
      data: {
        labels: data.dailyLabels,
        datasets: [{
          label: formatMetricLabel(data.dailyMetric || 'pm25'),
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
  const weeklyMetricSelect = document.getElementById('weeklyMetricSelect');
  let weeklyChart = null;
  if (weeklyCtx && data.weeklyLabels) {
    weeklyChart = new Chart(weeklyCtx, {
      type: 'bar',
      data: {
        labels: data.weeklyLabels,
        datasets: [{
          label: formatMetricLabel(data.weeklyMetric || 'pm25'),
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

  if (dailyMetricSelect) {
    dailyMetricSelect.value = data.dailyMetric || dailyMetricSelect.value;
    dailyMetricSelect.addEventListener('change', async (event) => {
      const metricKey = event.target.value;
      const series = await fetchSeries(data.dailyRoute, metricKey);
      if (!series || !dailyChart) {
        return;
      }
      dailyChart.data.labels = series.labels;
      dailyChart.data.datasets[0].data = series.values;
      dailyChart.data.datasets[0].label = formatMetricLabel(metricKey);
      dailyChart.update();
    });
  }

  if (weeklyMetricSelect) {
    weeklyMetricSelect.value = data.weeklyMetric || weeklyMetricSelect.value;
    weeklyMetricSelect.addEventListener('change', async (event) => {
      const metricKey = event.target.value;
      const series = await fetchSeries(data.weeklyRoute, metricKey);
      if (!series || !weeklyChart) {
        return;
      }
      weeklyChart.data.labels = series.labels;
      weeklyChart.data.datasets[0].data = series.values;
      weeklyChart.data.datasets[0].label = formatMetricLabel(metricKey);
      weeklyChart.update();
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
