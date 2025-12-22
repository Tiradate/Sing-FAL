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
    let rotateTimer = null;
    rotateBtn.addEventListener('click', () => {
      if (rotateTimer) {
        clearInterval(rotateTimer);
        rotateTimer = null;
        rotateBtn.classList.remove('btn-success');
        rotateBtn.classList.add('btn-outline-secondary');
        rotateBtn.textContent = 'Auto';
        return;
      }
      rotateBtn.classList.remove('btn-outline-secondary');
      rotateBtn.classList.add('btn-success');
      rotateBtn.textContent = 'Stop';
      rotateTimer = setInterval(() => {
        const index = data.floors.indexOf(floorSelect.value);
        const nextIndex = (index + 1) % data.floors.length;
        floorSelect.value = data.floors[nextIndex];
        window.location = `/?floor=${data.floors[nextIndex]}`;
      }, (data.autoRotateSeconds || 10) * 1000);
    });
    floorSelect.addEventListener('change', (event) => {
      const floor = event.target.value;
      window.location = `/?floor=${floor}`;
    });
  }
})();
