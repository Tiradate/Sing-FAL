(function () {
  const data = window.dashboardData || {};
  const metricOptions = data.metricOptions || {};
  const severityLevels = Array.isArray(data.severityLevels) ? data.severityLevels : [];

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

  const buildSeverityDatasets = (metricKey, labels) => {
    if (!data.showSeverityLines) {
      return [];
    }
    if (!Array.isArray(labels) || labels.length === 0) {
      return [];
    }
    return severityLevels
      .map((level) => {
        const value = level?.thresholds ? level.thresholds[metricKey] : null;
        if (value === null || value === undefined || Number.isNaN(value)) {
          return null;
        }
        return {
          type: 'line',
          label: `${level.label} threshold`,
          data: labels.map(() => value),
          borderColor: level.color || '#dc3545',
          borderWidth: 1.5,
          borderDash: [6, 4],
          pointRadius: 0,
          fill: false,
          tension: 0,
          order: 1,
        };
      })
      .filter(Boolean);
  };

  const applySeriesToChart = (chart, metricKey, series) => {
    chart.data.labels = series.labels;
    const baseDataset = chart.data.datasets[0];
    baseDataset.data = series.values;
    baseDataset.label = formatMetricLabel(metricKey);
    chart.data.datasets = [baseDataset, ...buildSeverityDatasets(metricKey, series.labels)];
    chart.update();
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
    const baseDataset = {
      label: formatMetricLabel(data.dailyMetric || 'pm25'),
      data: data.dailyValues,
      borderColor: '#0d6efd',
      backgroundColor: 'rgba(13, 110, 253, 0.1)',
      fill: true,
      tension: 0.3,
      order: 0,
    };
    const severityDatasets = buildSeverityDatasets(data.dailyMetric || 'pm25', data.dailyLabels);
    dailyChart = new Chart(dailyCtx, {
      type: 'line',
      data: {
        labels: data.dailyLabels,
        datasets: [baseDataset, ...severityDatasets],
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
    const baseDataset = {
      type: 'bar',
      label: formatMetricLabel(data.weeklyMetric || 'pm25'),
      data: data.weeklyValues,
      backgroundColor: '#198754',
      order: 0,
    };
    const severityDatasets = buildSeverityDatasets(data.weeklyMetric || 'pm25', data.weeklyLabels);
    weeklyChart = new Chart(weeklyCtx, {
      type: 'bar',
      data: {
        labels: data.weeklyLabels,
        datasets: [baseDataset, ...severityDatasets],
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
      applySeriesToChart(dailyChart, metricKey, series);
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
      applySeriesToChart(weeklyChart, metricKey, series);
    });
  }

  const floorSelect = document.getElementById('floorSelect');
  const rotateBtn = document.getElementById('floorRotate');
  if (data.floors) {
    const floorRoute = data.floorRoute || '/';
    const mapFullRoute = data.mapFullRoute || '/map';
    const rotateStorageKey = 'dashboardAutoRotate';
    const floorStorageKey = 'dashboardActiveFloor';
    const isFullMap = Boolean(data.isFullMap);
    let rotateTimer = null;
    let activeIndex = data.floors.indexOf(data.activeFloor);
    const floorFromQuery = Boolean(data.floorFromQuery);

    const buildFloorUrl = (baseUrl, floor) => {
      const url = new URL(baseUrl, window.location.origin);
      if (floor) {
        url.searchParams.set('floor', floor);
      } else {
        url.searchParams.delete('floor');
      }
      return url.toString();
    };

    const storedFloor = localStorage.getItem(floorStorageKey);

    if (data.activeFloor && (!storedFloor || floorFromQuery)) {
      localStorage.setItem(floorStorageKey, data.activeFloor);
    }

    if (!floorFromQuery && storedFloor && data.floors.includes(storedFloor) && storedFloor !== data.activeFloor) {
      window.location = buildFloorUrl(floorRoute, storedFloor);
      return;
    }

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
        localStorage.setItem(floorStorageKey, nextFloor);
        window.location = buildFloorUrl(floorRoute, nextFloor);
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
        if (currentFloor) {
          localStorage.setItem(floorStorageKey, currentFloor);
        }
        window.open(buildFloorUrl(mapFullRoute, currentFloor), '_blank');
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
        localStorage.setItem(floorStorageKey, floor);
        window.location = buildFloorUrl(floorRoute, floor);
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

  const sensorDetailsPanel = document.getElementById('sensorDetailsPanel');
  const sensorDetailsContent = sensorDetailsPanel?.querySelector('.sensor-details-content');
  const sensorDetailsPlaceholder = sensorDetailsPanel?.querySelector('.sensor-details-placeholder');
  if (sensorDetailsPanel && sensorDetailsContent) {
    const sensors = document.querySelectorAll('.sensor-icon');
    const updatePanel = (sensor) => {
      const tooltipTemplate = sensor.querySelector('template.sensor-tooltip-template');
      const tooltip = sensor.querySelector('.sensor-tooltip');
      if (!tooltipTemplate && !tooltip) {
        return;
      }
      if (tooltipTemplate) {
        sensorDetailsContent.innerHTML = tooltipTemplate.innerHTML.trim();
      } else if (tooltip) {
        sensorDetailsContent.innerHTML = tooltip.outerHTML;
      }
      sensorDetailsContent.hidden = false;
      if (sensorDetailsPlaceholder) {
        sensorDetailsPlaceholder.hidden = true;
      }
    };

    sensors.forEach((sensor) => {
      sensor.addEventListener('mouseenter', () => updatePanel(sensor));
      sensor.addEventListener('focus', () => updatePanel(sensor));
      sensor.addEventListener('click', () => updatePanel(sensor));
    });
  }
})();
