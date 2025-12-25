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
  if (data.floors) {
    const floorRoute = data.floorRoute || '/';
    const mapFullRoute = data.mapFullRoute || '/map';
    const rotateStorageKey = 'dashboardAutoRotate';
    const isFullMap = Boolean(data.isFullMap);
    let rotateTimer = null;
    let activeIndex = data.floors.indexOf(data.activeFloor);

    const updateRotateButton = (isActive) => {
      if (!rotateBtn) {
        return;
      }
      rotateBtn.classList.toggle('btn-secondary', isActive);
      rotateBtn.classList.toggle('btn-outline-secondary', !isActive);
      rotateBtn.textContent = 'Auto';
    };

    const startRotateTimer = () => {
      if (rotateTimer) {
        return;
      }
      rotateTimer = setInterval(() => {
        if (floorSelect) {
          activeIndex = data.floors.indexOf(floorSelect.value);
        }
        if (activeIndex === -1) {
          activeIndex = 0;
        }
        const nextIndex = (activeIndex + 1) % data.floors.length;
        const nextFloor = data.floors[nextIndex];
        activeIndex = nextIndex;
        window.location = `${floorRoute}?floor=${nextFloor}`;
      }, (data.autoRotateSeconds || 10) * 1000);
    };

    const startAutoRotate = () => {
      updateRotateButton(true);
      localStorage.setItem(rotateStorageKey, 'true');
      if (isFullMap) {
        startRotateTimer();
        return;
      }
      if (rotateBtn) {
        const currentFloor = floorSelect ? floorSelect.value : data.activeFloor;
        window.open(`${mapFullRoute}?floor=${currentFloor}`, '_blank');
      }
    };

    const stopAutoRotate = () => {
      if (rotateTimer) {
        clearInterval(rotateTimer);
        rotateTimer = null;
      }
      updateRotateButton(false);
      localStorage.setItem(rotateStorageKey, 'false');
    };

    if (rotateBtn) {
      rotateBtn.addEventListener('click', () => {
        if (localStorage.getItem(rotateStorageKey) === 'true') {
          stopAutoRotate();
        } else {
          startAutoRotate();
        }
      });
      updateRotateButton(localStorage.getItem(rotateStorageKey) === 'true');
    }

    if (isFullMap && localStorage.getItem(rotateStorageKey) === 'true') {
      startRotateTimer();
    }

    if (floorSelect) {
      floorSelect.addEventListener('change', (event) => {
        const floor = event.target.value;
        window.location = `${floorRoute}?floor=${floor}`;
      });
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
