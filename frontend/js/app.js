const appRoot = document.getElementById("app");

const routes = {
  "": "/frontend/pages/home.html",
  "/": "/frontend/pages/home.html",
  "/research": "/frontend/pages/research.html",
  "/memo": "/frontend/pages/memo.html",
  "/history": "/frontend/pages/history.html",
  "/settings": "/frontend/pages/settings.html",
};

function parseHash() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = hash.split("?");
  return { path, params: new URLSearchParams(qs || "") };
}

async function refreshBudgetPill() {
  try {
    const budget = await fetch("/api/budget").then((r) => r.json());
    const pill = document.getElementById("budget-pill");
    if (!pill) return;
    const cls = budget.remaining > 150 ? "budget-green" : budget.remaining > 50 ? "budget-amber" : "budget-red";
    pill.className = `budget-pill ${cls}`;
    pill.textContent = `${budget.remaining}/${budget.limit} calls remaining`;
  } catch (_err) {
    // no-op
  }
}

async function loadRoute() {
  // Stop any live research polling when navigating away
  if (window.AlphaResearch && window.AlphaResearch.stopPolling) {
    window.AlphaResearch.stopPolling();
  }
  const { path, params } = parseHash();
  const page = routes[path] || routes["/"];
  const html = await fetch(page).then((r) => r.text());
  appRoot.innerHTML = html;

  if (path === "/") {
    window.AlphaResearch.initHome();
  } else if (path === "/research") {
    window.AlphaResearch.initResearch(params.get("session_id"));
  } else if (path === "/memo") {
    window.AlphaMemo.initMemo(params.get("session_id"));
  } else if (path === "/history") {
    window.AlphaResearch.initHistory();
  } else if (path === "/settings") {
    window.AlphaSettings.initSettings();
  }
  refreshBudgetPill();
}

function initNetworkBackground() {
  const canvas = document.getElementById("network-canvas");
  if (!canvas || !window.THREE) return;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(65, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 80;

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const count = 120;
  const points = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    points[i * 3 + 0] = (Math.random() - 0.5) * 120;
    points[i * 3 + 1] = (Math.random() - 0.5) * 120;
    points[i * 3 + 2] = (Math.random() - 0.5) * 30;
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(points, 3));
  const mat = new THREE.PointsMaterial({ color: 0x00e5cc, size: 0.9 });
  const cloud = new THREE.Points(geom, mat);
  scene.add(cloud);

  const lineGeom = new THREE.BufferGeometry();
  lineGeom.setAttribute("position", new THREE.BufferAttribute(points, 3));
  const lineMat = new THREE.LineBasicMaterial({ color: 0x00e5cc, transparent: true, opacity: 0.12 });
  const lines = new THREE.Line(lineGeom, lineMat);
  scene.add(lines);

  function animate() {
    requestAnimationFrame(animate);
    cloud.rotation.y += 0.0009;
    lines.rotation.y -= 0.0005;
    renderer.render(scene, camera);
  }

  animate();
  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });
}

window.addEventListener("hashchange", loadRoute);
window.addEventListener("DOMContentLoaded", () => {
  initNetworkBackground();
  loadRoute();
  setInterval(refreshBudgetPill, 10000);
});