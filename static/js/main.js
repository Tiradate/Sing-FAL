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

  const alarmStatusRoute = data.alarmStatusRoute;
  if (alarmStatusRoute) {
    const initialAlarmCount = Number.isFinite(data.alarmCount) ? data.alarmCount : null;
    const initialHasCritical = Boolean(data.hasCritical);
    const initialLatestAlarmId = data.latestAlarmId ?? null;
    const pollIntervalMs = 30000;

    const shouldRefresh = (status) => {
      if (!status) {
        return false;
      }
      const latestAlarmId = status.latest_alarm_id ?? null;
      const alarmCount = Number.isFinite(status.alarm_count) ? status.alarm_count : null;
      const hasCritical = Boolean(status.has_critical);

      if (hasCritical && !initialHasCritical) {
        return true;
      }
      if (latestAlarmId && latestAlarmId !== initialLatestAlarmId) {
        return true;
      }
      if (alarmCount !== null && initialAlarmCount !== null && alarmCount > initialAlarmCount) {
        return true;
      }
      return false;
    };

    const checkAlarmStatus = async () => {
      const response = await fetch(alarmStatusRoute, { cache: 'no-store' });
      if (!response.ok) {
        return;
      }
      const status = await response.json();
      if (shouldRefresh(status)) {
        window.location.reload();
      }
    };

    setInterval(() => {
      checkAlarmStatus().catch(() => undefined);
    }, pollIntervalMs);
    checkAlarmStatus().catch(() => undefined);
  }

  const parsePercentValue = (value) => {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const ensureMapCanvas = (stage) => {
    let canvas = Array.from(stage.children).find((child) => child.classList?.contains('map-canvas'));
    if (canvas) {
      return canvas;
    }
    canvas = document.createElement('div');
    canvas.className = 'map-canvas';
    while (stage.firstChild) {
      canvas.appendChild(stage.firstChild);
    }
    stage.appendChild(canvas);
    return canvas;
  };

  const getMapBoundsFromImage = (img) => {
    const cached = img.dataset.cropBounds;
    if (cached) {
      try {
        return JSON.parse(cached);
      } catch (error) {
        img.dataset.cropBounds = '';
      }
    }
    if (!img.complete || !img.naturalWidth || !img.naturalHeight) {
      return null;
    }
    try {
      const probe = document.createElement('canvas');
      probe.width = img.naturalWidth;
      probe.height = img.naturalHeight;
      const context = probe.getContext('2d', { willReadFrequently: true });
      if (!context) {
        return null;
      }
      context.drawImage(img, 0, 0);
      const { data: pixels, width, height } = context.getImageData(0, 0, probe.width, probe.height);
      const whiteThreshold = 245;
      const alphaThreshold = 10;
      const stride = width * 4;
      let minX = width;
      let minY = height;
      let maxX = -1;
      let maxY = -1;

      for (let y = 0; y < height; y += 1) {
        const rowOffset = y * stride;
        for (let x = 0; x < width; x += 1) {
          const offset = rowOffset + (x * 4);
          const alpha = pixels[offset + 3];
          if (alpha <= alphaThreshold) {
            continue;
          }
          const red = pixels[offset];
          const green = pixels[offset + 1];
          const blue = pixels[offset + 2];
          if (red > whiteThreshold && green > whiteThreshold && blue > whiteThreshold) {
            continue;
          }
          if (x < minX) {
            minX = x;
          }
          if (y < minY) {
            minY = y;
          }
          if (x > maxX) {
            maxX = x;
          }
          if (y > maxY) {
            maxY = y;
          }
        }
      }

      const fallbackBounds = {
        left: 0,
        top: 0,
        width,
        height,
        fullWidth: width,
        fullHeight: height,
      };
      if (maxX < minX || maxY < minY) {
        img.dataset.cropBounds = JSON.stringify(fallbackBounds);
        return fallbackBounds;
      }

      const padding = 24;
      const bounds = {
        left: Math.max(0, minX - padding),
        top: Math.max(0, minY - padding),
        width: Math.min(width, (maxX - minX) + (padding * 2)),
        height: Math.min(height, (maxY - minY) + (padding * 2)),
        fullWidth: width,
        fullHeight: height,
      };
      img.dataset.cropBounds = JSON.stringify(bounds);
      return bounds;
    } catch (error) {
      return null;
    }
  };

  const expandBoundsForMarkers = (stage, bounds) => {
    const nextBounds = { ...bounds };
    const markerPadding = 40;
    stage.querySelectorAll('.sensor-icon, .logo-icon').forEach((marker) => {
      if (marker.dataset.originalLeft === undefined) {
        marker.dataset.originalLeft = marker.style.left || '';
      }
      if (marker.dataset.originalTop === undefined) {
        marker.dataset.originalTop = marker.style.top || '';
      }
      const leftPct = parsePercentValue(marker.dataset.originalLeft);
      const topPct = parsePercentValue(marker.dataset.originalTop);
      if (leftPct === null || topPct === null) {
        return;
      }
      const markerX = (leftPct / 100) * bounds.fullWidth;
      const markerY = (topPct / 100) * bounds.fullHeight;
      nextBounds.left = Math.max(0, Math.min(nextBounds.left, markerX - markerPadding));
      nextBounds.top = Math.max(0, Math.min(nextBounds.top, markerY - markerPadding));
      const maxX = Math.min(bounds.fullWidth, Math.max(nextBounds.left + nextBounds.width, markerX + markerPadding));
      const maxY = Math.min(bounds.fullHeight, Math.max(nextBounds.top + nextBounds.height, markerY + markerPadding));
      nextBounds.width = maxX - nextBounds.left;
      nextBounds.height = maxY - nextBounds.top;
    });
    return nextBounds;
  };

  const applyResponsiveMapCrop = (stage) => {
    if (!stage || stage.closest('.map-editor')) {
      return;
    }
    const img = stage.querySelector('.map-image');
    if (!img) {
      return;
    }
    const baseBounds = getMapBoundsFromImage(img);
    if (!baseBounds) {
      return;
    }
    const bounds = expandBoundsForMarkers(stage, baseBounds);
    const widthRatio = bounds.width / bounds.fullWidth;
    const heightRatio = bounds.height / bounds.fullHeight;
    if (widthRatio >= 0.98 && heightRatio >= 0.98) {
      return;
    }

    const canvas = ensureMapCanvas(stage);
    stage.classList.add('is-auto-cropped');
    stage.style.aspectRatio = `${bounds.width} / ${bounds.height}`;
    canvas.style.aspectRatio = `${bounds.fullWidth} / ${bounds.fullHeight}`;
    canvas.style.width = `${(bounds.fullWidth / bounds.width) * 100}%`;
    canvas.style.left = `${-(bounds.left / bounds.width) * 100}%`;
    canvas.style.top = `${-(bounds.top / bounds.height) * 100}%`;
  };

  const initResponsiveMaps = () => {
    document.querySelectorAll('.map-stage').forEach((stage) => {
      const img = stage.querySelector('.map-image');
      if (!img) {
        return;
      }
      if (img.decode) {
        img.decode().then(
          () => applyResponsiveMapCrop(stage),
          () => applyResponsiveMapCrop(stage)
        );
        return;
      }
      if (img.complete && img.naturalWidth) {
        applyResponsiveMapCrop(stage);
        return;
      }
      img.addEventListener('load', () => applyResponsiveMapCrop(stage), { once: true });
    });
  };

  initResponsiveMaps();
  window.addEventListener('load', initResponsiveMaps, { once: true });
  window.addEventListener('pageshow', initResponsiveMaps);

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
